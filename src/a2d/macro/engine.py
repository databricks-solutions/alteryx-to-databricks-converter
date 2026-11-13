"""Resolve, parse, and inline Alteryx macros (.yxmc) into a parent IR DAG.

Inlining maps the parent's connections through the macro's MacroInput/
MacroOutput boundaries: whatever fed the macro-call node now feeds the macro's
input boundary's successors, and the macro's output boundary's predecessors now
feed whatever the call node fed. The boundary nodes themselves are dropped —
they are Alteryx plumbing with no data transformation.

Macros that call other macros are expanded too, to a fixed depth, and a macro
that ends up calling itself is reported rather than looped on.

Only standard macros are inlined. A batch macro runs once per value of its
control parameter and an iterative macro re-runs on its own output; one inlined
pass reproduces neither, so those calls are left unconverted and reported. A
standard macro that rewrites its tools from the calling tool's settings is
inlined with the values saved in the macro, and a note says to check them.

Every inlined macro instance gets its own band of node ids (see ``_ID_BAND``),
so ids never collide with the parent's or with another instance's, however
deeply macros nest.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry
from a2d.exceptions import A2dError
from a2d.ir.graph import EdgeInfo, WorkflowDAG
from a2d.ir.nodes import IRNode, MacroIONode
from a2d.macro.detect import MacroCall, find_macro_calls, function_name_for
from a2d.macro.models import (
    ExpansionResult,
    MacroBoundary,
    MacroDefinition,
    UnresolvedMacro,
)
from a2d.parser.schema import ParsedWorkflow
from a2d.parser.workflow_parser import WorkflowParser

logger = logging.getLogger("a2d.macro.engine")

# Inlined instance k (k = 1, 2, ...) gets ids k * _ID_BAND + original_id. Original
# Alteryx ToolIDs are far below 1e6, so the bands never overlap.
_ID_BAND = 1_000_000

# How deep macros may call macros before expansion stops (and says so).
MAX_NESTING_DEPTH = 8

# Visual-only tool types carried over from the pipeline's DAG builder.
_SKIP_TYPES = frozenset({"ToolContainer", "Tab"})


def _is_within(path: Path, root: Path) -> bool:
    """True if *path* is *root* itself or lies inside it (both already resolved)."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _casefold_find(root: Path, parts: list[str]) -> Path | None:
    """Walk *parts* under *root*, matching each name case-insensitively.

    Alteryx runs on Windows, where ``Macros\\Cleanse.yxmc`` and
    ``macros/cleanse.yxmc`` are the same file; on a Linux server they aren't, so
    an exact-case lookup alone misses macros whose reference differs in case
    from the file name. ``..`` is refused outright (containment is checked by
    the caller as well).
    """
    current = root
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            return None
        folded = part.casefold()
        try:
            match = next((c for c in current.iterdir() if c.name.casefold() == folded), None)
        except OSError:
            return None
        if match is None:
            return None
        current = match
    return current


def _where(node_id: int) -> str:
    return f"tool {node_id}" if node_id < _ID_BAND else "a tool inside another macro"


def _macro_name(macro_path: str) -> str:
    return macro_path.replace("\\", "/").rsplit("/", 1)[-1]


# What the user can do about each kind of unexpanded call.
_NEXT_STEP = {
    "missing": "That tool is left unconverted; supply the .yxmc with the workflow to convert it.",
    "batch": "That tool is left unconverted, to rewrite by hand (for example as a loop over the control values).",
    "iterative": "That tool is left unconverted, to rewrite by hand (for example as a loop or a Lakeflow Job).",
}


def unresolved_macro_warning(unresolved: UnresolvedMacro) -> str:
    """A user-facing warning for a macro call that was left unexpanded."""
    next_step = _NEXT_STEP.get(unresolved.kind, "That tool is left unconverted.")
    return (
        f"Macro {_macro_name(unresolved.macro_path)} ({_where(unresolved.call_node_id)}) wasn't expanded: "
        f"{unresolved.reason}. {next_step}"
    )


def _macro_kind(parsed: ParsedWorkflow) -> tuple[str, bool]:
    """``(kind, takes_settings)`` from a macro's own RuntimeProperties."""
    runtime = parsed.properties.get("RuntimeProperties") if isinstance(parsed.properties, dict) else None
    if not isinstance(runtime, dict):
        return "standard", False
    kind = "batch" if "BatchMacro" in runtime else "iterative" if "IterativeMacro" in runtime else "standard"
    return kind, bool(runtime.get("Actions"))


_LOOPING_REASON = {
    "batch": "it's a batch macro, which Alteryx runs once for each value of its control parameter",
    "iterative": "it's an iterative macro, which Alteryx re-runs on its own output until a condition is met",
}


@dataclass
class _Expansion:
    """Running state for one :meth:`MacroExpansionEngine.expand` call."""

    definitions: dict[str, MacroDefinition] = field(default_factory=dict)
    unresolved: list[UnresolvedMacro] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    expanded: int = 0
    bands_used: int = 0


class MacroExpansionEngine:
    """Expand macro calls in a workflow by inlining referenced .yxmc DAGs.

    Macros are looked up next to the workflow, then in ``search_paths`` (for
    example a project's shared macros). A nested macro is looked up next to the
    macro that calls it first.
    """

    def __init__(self, config: ConversionConfig | None = None, search_paths: list[Path] | None = None) -> None:
        self.config = config or ConversionConfig()
        self._parser = WorkflowParser()
        self._search_paths = list(search_paths) if search_paths else []
        # resolved macro file path -> parsed MacroDefinition, cached across calls.
        self._defn_cache: dict[str, MacroDefinition] = {}

    # ── Public API ─────────────────────────────────────────────────────────

    def expand(self, workflow: ParsedWorkflow, base_dag: WorkflowDAG) -> ExpansionResult:
        """Inline every resolvable macro call in *workflow* into *base_dag*.

        *base_dag* is the parent's already-built IR DAG (macro-call nodes present
        as UnsupportedNode/other). Returns a new DAG with macros inlined; the
        input DAG is not mutated.
        """
        dag = _clone_dag(base_dag)
        calls = find_macro_calls(workflow)
        if not calls:
            return ExpansionResult(dag=dag)

        parent_dir = Path(workflow.file_path).parent if workflow.file_path not in ("", "<string>") else None
        state = _Expansion()
        for call in calls:
            self._expand_call(dag, call, call.node_id, [parent_dir] if parent_dir else [], (), state)

        return ExpansionResult(
            dag=dag,
            definitions=list(state.definitions.values()),
            expanded_calls=state.expanded,
            unresolved=state.unresolved,
            notes=state.notes,
        )

    def _expand_call(
        self,
        dag: WorkflowDAG,
        call: MacroCall,
        node_id: int,
        dirs: list[Path],
        chain: tuple[str, ...],
        state: _Expansion,
    ) -> None:
        """Inline one call (the node *node_id* in *dag*), then the calls inside it.

        *dirs* are where to look first (the caller's directory, then the
        top-level workflow's); *chain* is the macros already being expanded
        around this call, to catch a macro that calls itself.
        """

        def unresolved(reason: str, kind: str) -> None:
            state.unresolved.append(UnresolvedMacro(call.macro_path, node_id, reason, kind))
            _set_reason(dag, node_id, f"Macro {_macro_name(call.macro_path)} wasn't expanded: {reason}.")
            logger.warning("Could not expand macro %s at node %d: %s", call.macro_path, node_id, reason)

        if len(chain) >= MAX_NESTING_DEPTH:
            unresolved(f"macros are nested more than {MAX_NESTING_DEPTH} levels deep", "too_deep")
            return
        try:
            definition = self._load_definition(call, dirs)
        except A2dError as e:
            unresolved(str(e), "missing")
            return
        if definition.source_path in chain:
            unresolved("the macro calls itself (directly or through another macro)", "self_call")
            return
        if definition.kind in _LOOPING_REASON:
            unresolved(_LOOPING_REASON[definition.kind], definition.kind)
            return

        state.bands_used += 1
        offset = state.bands_used * _ID_BAND
        state.definitions.setdefault(definition.source_path, definition)
        self._inline(dag, node_id, definition, offset)
        state.expanded += 1
        if definition.takes_settings:
            where = _where(node_id)
            state.notes.append(
                f"Macro {_macro_name(call.macro_path)} ({where}) was inlined with the values saved in the macro, "
                f"but it also takes settings from the tool that calls it: check the inlined steps against "
                f"{where}'s configuration in Alteryx."
            )

        # Calls inside the macro were copied in with the rest of its interior,
        # re-based by the same offset; expand them in place.
        inner_dirs = [Path(definition.source_path).parent, *dirs]
        for inner in definition.calls:
            self._expand_call(dag, inner, inner.node_id + offset, inner_dirs, (*chain, definition.source_path), state)

    # ── Resolution + parsing ───────────────────────────────────────────────

    def _load_definition(self, call: MacroCall, dirs: list[Path]) -> MacroDefinition:
        """Resolve and parse a macro, caching by the file it resolves to."""
        resolved = self._resolve_path(call.macro_path, dirs)
        if resolved is None:
            raise A2dError(f"macro file not found: {call.macro_path}")

        key = str(resolved)
        cached = self._defn_cache.get(key)
        if cached is not None:
            return cached

        parsed = self._parser.parse(resolved)
        macro_dag = self._build_macro_dag(parsed)
        inputs, outputs = _boundaries(macro_dag)
        kind, takes_settings = _macro_kind(parsed)

        definition = MacroDefinition(
            macro_path=call.macro_path.replace("\\", "/").lower(),
            source_path=key,
            function_name=function_name_for(call.macro_path),
            dag=macro_dag,
            inputs=inputs,
            outputs=outputs,
            node_count=macro_dag.node_count,
            calls=find_macro_calls(parsed),
            kind=kind,
            takes_settings=takes_settings,
        )
        self._defn_cache[key] = definition
        return definition

    def _resolve_path(self, macro_path: str, parent_dir: Path | list[Path] | None) -> Path | None:
        """Find the .yxmc on disk, confined to trusted roots.

        Security: a workflow is untrusted input (uploaded to the hosted App), and
        its macro references are attacker-controllable. Resolution is therefore
        confined to *parent_dir* (one directory or several, searched in order)
        plus any explicit ``search_paths``.
        Absolute macro paths and any reference that escapes those roots (``..``,
        symlink, etc.) are rejected, so a crafted workflow cannot read arbitrary
        server files (e.g. ``/etc/passwd`` or ``../../secret.yxmc``).

        Alteryx authored on Windows writes ``MacroPath`` with backslash separators
        (e.g. ``_externals\\1\\Ingest.yxmc``); the same file is extracted from the
        ``.yxzp`` under forward-slash names, so we normalize ``\\`` → ``/`` before
        building the path — otherwise POSIX treats the whole string as one literal
        filename and the macro is never found on a Linux server. Windows paths
        are also case-insensitive, so when no exact match exists the same
        lookups are retried ignoring case.
        """
        macro_path = macro_path.replace("\\", "/")
        candidate = Path(macro_path)

        # Allowed roots, resolved once.
        if parent_dir is None:
            allowed_roots: list[Path] = []
        elif isinstance(parent_dir, Path):
            allowed_roots = [parent_dir]
        else:
            allowed_roots = list(parent_dir)
        allowed_roots.extend(self._search_paths)
        resolved_roots: list[Path] = []
        for root in allowed_roots:
            try:
                resolved_roots.append(root.resolve())
            except (OSError, RuntimeError):
                continue
        if not resolved_roots:
            return None

        def accept(path: Path | None) -> Path | None:
            if path is None:
                return None
            try:
                resolved = path.resolve()
            except (OSError, RuntimeError):
                return None
            # Must stay within one of the allowed roots after resolution.
            if not any(_is_within(resolved, root) for root in resolved_roots):
                return None
            return resolved if resolved.is_file() else None

        # Candidate paths, always joined onto a trusted root. An absolute
        # macro_path must never be joined verbatim (it would win over the root),
        # so absolute references fall back to the basename inside each root.
        name = candidate.name  # basename is always safe to join
        relative_parts = [] if candidate.is_absolute() else list(candidate.parts)
        for root in resolved_roots:
            if relative_parts:
                found = accept(root / macro_path)
                if found:
                    return found
            found = accept(root / name)
            if found:
                return found
        for root in resolved_roots:
            if relative_parts:
                found = accept(_casefold_find(root, relative_parts))
                if found:
                    return found
            found = accept(_casefold_find(root, [name]))
            if found:
                return found
        return None

    def _build_macro_dag(self, parsed: ParsedWorkflow) -> WorkflowDAG:
        """Build an IR DAG for a macro, mirroring the pipeline's builder."""
        dag = WorkflowDAG()
        disabled: set[int] = set()
        for node in parsed.nodes:
            if node.disabled:
                disabled.add(node.tool_id)
                continue
            if node.tool_type in _SKIP_TYPES:
                continue
            dag.add_node(ConverterRegistry.convert_node(node, self.config))
        node_ids = set(dag.all_node_ids())
        for conn in parsed.connections:
            src, dst = conn.origin.tool_id, conn.destination.tool_id
            if src in node_ids and dst in node_ids:
                dag.add_edge(src, dst, conn.origin.anchor_name, conn.destination.anchor_name)
        return dag

    # ── Inlining ───────────────────────────────────────────────────────────

    def _inline(self, dag: WorkflowDAG, call_node_id: int, definition: MacroDefinition, offset: int) -> None:
        """Splice the macro's interior into *dag* in place of the call node."""
        boundary_ids = {b.node_id for b in definition.inputs} | {b.node_id for b in definition.outputs}

        # 1. Copy interior (non-boundary) macro nodes into the parent, re-based.
        for node in definition.dag.all_nodes():
            if node.node_id in boundary_ids:
                continue
            dag.add_node(_rebased_copy(node, offset))

        # 2. Copy interior→interior edges.
        for src, dst, info in definition.dag.all_edges():
            if src in boundary_ids or dst in boundary_ids:
                continue
            dag.add_edge(src + offset, dst + offset, info.origin_anchor, info.destination_anchor, info.is_wireless)

        # 3. Rewire the parent's upstream (feeding the call) into the macro's
        #    input-boundary successors.
        upstream = _predecessor_edges(dag, call_node_id)
        input_targets = _boundary_neighbors(definition, definition.inputs, downstream=True)
        for up_src, up_info in upstream:
            for tgt, tgt_info in input_targets:
                dag.add_edge(up_src, tgt + offset, up_info.origin_anchor, tgt_info.destination_anchor)

        # 4. Rewire the macro's output-boundary predecessors into the parent's
        #    downstream (fed by the call).
        downstream = _successor_edges(dag, call_node_id)
        output_sources = _boundary_neighbors(definition, definition.outputs, downstream=False)
        for src, src_info in output_sources:
            for down_dst, down_info in downstream:
                dag.add_edge(src + offset, down_dst, src_info.origin_anchor, down_info.destination_anchor)

        # 5. Remove the original call node (and its now-dangling edges).
        dag.remove_node(call_node_id)


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------


def _set_reason(dag: WorkflowDAG, node_id: int, reason: str) -> None:
    """Record on an unexpanded call node why it wasn't expanded (on a copy: the
    clone shares node objects with the caller's DAG)."""
    import copy

    try:
        node = dag.get_node(node_id)
    except KeyError:
        return
    if not hasattr(node, "unsupported_reason"):
        return
    updated = copy.copy(node)
    updated.unsupported_reason = reason  # type: ignore[attr-defined]
    dag.replace_node(updated)


def _clone_dag(dag: WorkflowDAG) -> WorkflowDAG:
    """Deep-ish copy: shares IRNode instances but a fresh graph structure."""
    clone = WorkflowDAG()
    for node in dag.all_nodes():
        clone.add_node(node)
    for src, dst, info in dag.all_edges():
        clone.add_edge(src, dst, info.origin_anchor, info.destination_anchor, info.is_wireless)
    return clone


def _rebased_copy(node: IRNode, offset: int) -> IRNode:
    """Return a shallow copy of *node* with its id shifted by *offset*."""
    import copy

    new = copy.copy(node)
    new.node_id = node.node_id + offset
    return new


def _boundaries(macro_dag: WorkflowDAG) -> tuple[list[MacroBoundary], list[MacroBoundary]]:
    """Split a macro DAG's MacroIONodes into ordered input/output boundaries."""
    inputs: list[MacroBoundary] = []
    outputs: list[MacroBoundary] = []
    for node in macro_dag.all_nodes():
        if isinstance(node, MacroIONode):
            boundary = MacroBoundary(node_id=node.node_id, name=node.field_name, direction=node.direction)
            (inputs if node.direction == "input" else outputs).append(boundary)
    inputs.sort(key=lambda b: b.node_id)
    outputs.sort(key=lambda b: b.node_id)
    return inputs, outputs


def _boundary_neighbors(
    definition: MacroDefinition,
    boundaries: list[MacroBoundary],
    *,
    downstream: bool,
) -> list[tuple[int, EdgeInfo]]:
    """Interior nodes adjacent to the given boundaries.

    For input boundaries (downstream=True) these are the boundary's successors;
    for output boundaries (downstream=False) the boundary's predecessors. Each
    returned tuple is ``(interior_node_id, EdgeInfo)``.
    """
    result: list[tuple[int, EdgeInfo]] = []
    for boundary in boundaries:
        for src, dst, info in definition.dag.all_edges():
            if downstream and src == boundary.node_id:
                result.append((dst, info))
            elif not downstream and dst == boundary.node_id:
                result.append((src, info))
    return result


def _predecessor_edges(dag: WorkflowDAG, node_id: int) -> list[tuple[int, EdgeInfo]]:
    """(source_id, EdgeInfo) for every edge feeding *node_id*."""
    return [(src, info) for src, dst, info in dag.all_edges() if dst == node_id]


def _successor_edges(dag: WorkflowDAG, node_id: int) -> list[tuple[int, EdgeInfo]]:
    """(dest_id, EdgeInfo) for every edge leaving *node_id*."""
    return [(dst, info) for src, dst, info in dag.all_edges() if src == node_id]
