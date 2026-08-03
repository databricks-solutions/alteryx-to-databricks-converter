"""Resolve, parse, and inline Alteryx macros (.yxmc) into a parent IR DAG.

Inlining maps the parent's connections through the macro's MacroInput/
MacroOutput boundaries: whatever fed the macro-call node now feeds the macro's
input boundary's successors, and the macro's output boundary's predecessors now
feed whatever the call node fed. The boundary nodes themselves are dropped —
they are Alteryx plumbing with no data transformation.

Node ids from the macro are re-based by a large offset so they never collide
with the parent's ids (or another macro's, when several are inlined).
"""

from __future__ import annotations

import logging
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

# Each inlined macro instance gets ids in a disjoint band: base = (instance+1)
# * _ID_BAND + original_id. 1e6 comfortably exceeds any real Alteryx ToolID.
_ID_BAND = 1_000_000

# Visual-only tool types carried over from the pipeline's DAG builder.
_SKIP_TYPES = frozenset({"ToolContainer", "Tab"})


class MacroExpansionEngine:
    """Expand macro calls in a workflow by inlining referenced .yxmc DAGs."""

    def __init__(self, config: ConversionConfig | None = None, search_paths: list[Path] | None = None) -> None:
        self.config = config or ConversionConfig()
        self._parser = WorkflowParser()
        self._search_paths = search_paths or []
        # macro_path (normalized) -> parsed MacroDefinition, cached across calls.
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

        definitions: dict[str, MacroDefinition] = {}
        unresolved: list[UnresolvedMacro] = []
        expanded = 0

        for instance, call in enumerate(calls):
            try:
                definition = self._load_definition(call, parent_dir)
            except A2dError as e:
                unresolved.append(UnresolvedMacro(call.macro_path, call.node_id, str(e)))
                logger.warning("Could not expand macro %s at node %d: %s", call.macro_path, call.node_id, e)
                continue

            definitions.setdefault(definition.macro_path, definition)
            self._inline(dag, call, definition, instance)
            expanded += 1

        return ExpansionResult(
            dag=dag,
            definitions=list(definitions.values()),
            expanded_calls=expanded,
            unresolved=unresolved,
        )

    # ── Resolution + parsing ───────────────────────────────────────────────

    def _load_definition(self, call: MacroCall, parent_dir: Path | None) -> MacroDefinition:
        """Resolve and parse a macro, caching by normalized path."""
        key = call.macro_path.replace("\\", "/").lower()
        cached = self._defn_cache.get(key)
        if cached is not None:
            return cached

        resolved = self._resolve_path(call.macro_path, parent_dir)
        if resolved is None:
            raise A2dError(f"macro file not found: {call.macro_path}")

        parsed = self._parser.parse(resolved)
        macro_dag = self._build_macro_dag(parsed)
        inputs, outputs = _boundaries(macro_dag)

        definition = MacroDefinition(
            macro_path=key,
            source_path=str(resolved),
            function_name=function_name_for(call.macro_path),
            dag=macro_dag,
            inputs=inputs,
            outputs=outputs,
            node_count=macro_dag.node_count,
        )
        self._defn_cache[key] = definition
        return definition

    def _resolve_path(self, macro_path: str, parent_dir: Path | None) -> Path | None:
        """Find the .yxmc on disk. Tries absolute, parent-relative, then search paths."""
        candidate = Path(macro_path)
        tries: list[Path] = []
        if candidate.is_absolute():
            tries.append(candidate)
        if parent_dir is not None:
            tries.append(parent_dir / macro_path)
            tries.append(parent_dir / candidate.name)
        for base in self._search_paths:
            tries.append(base / macro_path)
            tries.append(base / candidate.name)

        for t in tries:
            if t.is_file():
                return t
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

    def _inline(self, dag: WorkflowDAG, call: MacroCall, definition: MacroDefinition, instance: int) -> None:
        """Splice the macro's interior into *dag* in place of the call node."""
        offset = (instance + 1) * _ID_BAND

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
        upstream = _predecessor_edges(dag, call.node_id)
        input_targets = _boundary_neighbors(definition, definition.inputs, downstream=True)
        for up_src, up_info in upstream:
            for tgt, tgt_info in input_targets:
                dag.add_edge(up_src, tgt + offset, up_info.origin_anchor, tgt_info.destination_anchor)

        # 4. Rewire the macro's output-boundary predecessors into the parent's
        #    downstream (fed by the call).
        downstream = _successor_edges(dag, call.node_id)
        output_sources = _boundary_neighbors(definition, definition.outputs, downstream=False)
        for src, src_info in output_sources:
            for down_dst, down_info in downstream:
                dag.add_edge(src + offset, down_dst, src_info.origin_anchor, down_info.destination_anchor)

        # 5. Remove the original call node (and its now-dangling edges).
        dag.remove_node(call.node_id)


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------


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
