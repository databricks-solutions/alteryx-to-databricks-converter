"""Categorize raw converter / generator warnings for human-friendly display.

This is a Python port of ``frontend/src/lib/warning-parsing.ts``. It takes the
free-form warning strings the pipeline emits and turns them into structured
records grouped by user-facing bucket so the CLI (and any other consumer) can
render plain-English copy with appropriate severity.

Pure module — no I/O, no rich, no dependency on :mod:`a2d.pipeline`. Safe to
call from generators, the server layer, or the CLI printers.

Examples of strings this parses:

* ``"Unsupported node 765: No converter for tool type: Unknown"``
* ``"No DLT generator for DynamicRenameNode (node 808)"``
* ``"Filter expression fallback for node 679"``
* ``"Graph has 2 disconnected data components: [4, 14, ...], [765, 833]"``
* ``"DynamicRename node 808 (from-input mode): manual DLT review needed"``

Anything that doesn't match a known shape falls into the ``other`` bucket and
is rendered verbatim.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

# ── Format-id → human label (mirror of ``frontend/src/lib/constants.ts``) ──
FORMAT_LABELS: dict[str, str] = {
    "pyspark": "PySpark",
    "dlt": "Spark Declarative Pipelines",
    "sql": "Spark SQL",
    "lakeflow": "Lakeflow Designer",
}


def format_label(format_id: str) -> str:
    """Return the friendly label for a format id; falls back to the id."""
    return FORMAT_LABELS.get(format_id, format_id)


WarningKind = Literal[
    "unsupported_tool",
    "missing_generator",
    "expression_fallback",
    "local_path",
    "disconnected_components",
    "other",
]
WarningSeverity = Literal["info", "review", "blocker"]


@dataclass(frozen=True)
class ParsedWarning:
    """Structured representation of a single warning string."""

    kind: WarningKind
    severity: WarningSeverity
    raw: str
    title: str
    detail: str
    node_id: int | None = None
    tool: str | None = None
    generator: str | None = None
    components: tuple[tuple[int, ...], ...] | None = None


@dataclass
class CategorizedWarnings:
    """Warnings grouped by user-facing bucket."""

    unsupported: list[ParsedWarning] = field(default_factory=list)
    review: list[ParsedWarning] = field(default_factory=list)
    graph: list[ParsedWarning] = field(default_factory=list)
    other: list[ParsedWarning] = field(default_factory=list)
    total: int = 0
    manual_review_node_count: int = 0


# Regexes intentionally mirror the TypeScript versions character-for-character
# so we stay in lockstep with the UI.
# PySpark generator emits ``Unsupported node N (Tool): No converter ...`` with
# the tool name in parens; SQL/DLT emit the older ``Unsupported node N: ...``
# shape. Accept both — the parens group is optional; tool name is captured
# when present and preferred over the trailing ``tool type: X`` form.
_RE_UNSUPPORTED = re.compile(
    r"^Unsupported node (\d+)(?:\s*\(([^)]+)\))?:\s*No converter for tool type:\s*(.+?)\s*$",
    re.IGNORECASE,
)
_RE_NO_GENERATOR = re.compile(
    r"^No (PySpark|DLT|SQL|Lakeflow)\s+generator\s+for\s+(\w+)\s*\(node\s*(\d+)\)",
    re.IGNORECASE,
)
_RE_EXPR_FALLBACK = re.compile(
    r"^(\w+)\s+expression\s+fallback\s+for\s+node\s+(\d+)",
    re.IGNORECASE,
)
_RE_DISCONNECTED = re.compile(
    r"^Graph has (\d+)\s+disconnected\s+data\s+components?:\s*(.*)$",
    re.IGNORECASE,
)
# Generators flag local/UNC paths that need to be migrated to cloud storage
# (UC volumes, S3, ADLS). Informational, not a blocker — but the user must
# update the path before running.
_RE_LOCAL_PATH = re.compile(
    r"^(Input|Output) node (\d+):\s*path\s*'(.+?)'\s*is a local/UNC path",
    re.IGNORECASE,
)
# DLT/SQL generators emit this when a DynamicRename node can't be auto-translated
# (the rename map is data-driven; the generator produces a placeholder). E.g.:
#   "DynamicRename node 808 (from-input mode): manual DLT review needed"
#   "DynamicRename node 452 (FirstRow mode): manual SQL rewrite needed"
# Source: src/a2d/generators/sql.py + src/a2d/generators/dlt.py.
_RE_DYNAMIC_RENAME = re.compile(
    r"^DynamicRename node (\d+) \(([^)]+) mode\):\s*(.+?)$",
    re.IGNORECASE,
)
# Join visitor flags a join with no resolvable keys (the user must fill in
# the join condition manually). Emitted by pyspark.py:1014. E.g.:
#   "Join node 286: no join keys found — manual condition required"
_RE_JOIN_NO_KEYS = re.compile(
    r"^Join node (\d+):\s*no join keys found\s*[—\-]+\s*manual condition required",
    re.IGNORECASE,
)


def _pretty_tool(tool: str) -> str:
    """Strip a trailing ``Node`` suffix from IR class names."""
    return tool[:-4] if tool.endswith("Node") else tool


def _parse_component_list(s: str) -> tuple[tuple[int, ...], ...]:
    """Parse ``"[1, 2, 3], [4, 5]"`` into ``((1, 2, 3), (4, 5))``."""
    out: list[tuple[int, ...]] = []
    for match in re.finditer(r"\[([^\]]*)\]", s):
        ids: list[int] = []
        for tok in match.group(1).split(","):
            tok = tok.strip()
            if not tok:
                continue
            try:
                ids.append(int(tok))
            except ValueError:
                # Skip placeholder tokens like "..." silently — matches TS
                # behaviour where ``Number("...")`` returns NaN and is filtered.
                continue
        if ids:
            out.append(tuple(ids))
    return tuple(out)


def parse_warning(raw: str) -> ParsedWarning:
    """Classify a single raw warning string."""
    trimmed = raw.strip()

    m = _RE_UNSUPPORTED.match(trimmed)
    if m:
        node_id = int(m.group(1))
        # Group 2 is the optional parenthesized tool name (PySpark style);
        # group 3 is the trailing ``tool type: X``. Prefer the parens form.
        tool = m.group(2) or m.group(3)
        return ParsedWarning(
            kind="unsupported_tool",
            severity="blocker",
            raw=raw,
            node_id=node_id,
            tool=tool,
            title=f"Node {node_id} ({tool}) — no converter",
            detail=(
                f'a2d does not yet support the Alteryx tool "{tool}". The '
                f"generated code skips this node, so the dataflow downstream "
                f"of node {node_id} will be incomplete. You must replace "
                "this step manually."
            ),
        )

    m = _RE_NO_GENERATOR.match(trimmed)
    if m:
        generator = m.group(1).lower()
        tool = m.group(2)
        node_id = int(m.group(3))
        gen_label = format_label(generator)
        return ParsedWarning(
            kind="missing_generator",
            severity="review",
            raw=raw,
            node_id=node_id,
            tool=tool,
            generator=generator,
            title=(f"Node {node_id} ({_pretty_tool(tool)}) — {gen_label} generator missing"),
            detail=(
                f"a2d understood this Alteryx tool but the {gen_label} "
                "generator does not yet emit code for it. The output "
                "contains a comment placeholder. Other formats (e.g. "
                "PySpark) may still cover this node — check the other tabs."
            ),
        )

    m = _RE_EXPR_FALLBACK.match(trimmed)
    if m:
        tool = m.group(1)
        node_id = int(m.group(2))
        return ParsedWarning(
            kind="expression_fallback",
            severity="review",
            raw=raw,
            node_id=node_id,
            tool=tool,
            title=f"Node {node_id} ({tool}) — expression fallback",
            detail=(
                f"a2d couldn't fully translate one of the Alteryx "
                f"expressions on this {tool} node. It emitted a best-effort "
                "translation; verify the logic before running."
            ),
        )

    m = _RE_LOCAL_PATH.match(trimmed)
    if m:
        direction = m.group(1)  # "Input" | "Output"
        node_id = int(m.group(2))
        path = m.group(3)
        return ParsedWarning(
            kind="local_path",
            severity="review",
            raw=raw,
            node_id=node_id,
            title=f"Node {node_id} ({direction}) — local/UNC path",
            detail=(
                f"This {direction.lower()} references a local or UNC path "
                f'("{path}") which Databricks compute cannot read. Migrate '
                "the file to a cloud location (Unity Catalog volume, S3, "
                "ADLS, GCS) and update the path in the generated code "
                "before running."
            ),
        )

    m = _RE_DISCONNECTED.match(trimmed)
    if m:
        count = int(m.group(1))
        components = _parse_component_list(m.group(2))
        return ParsedWarning(
            kind="disconnected_components",
            severity="info",
            raw=raw,
            components=components,
            title=f"{count} disconnected dataflows",
            detail=(
                f"Your workflow has {count} independent dataflows that "
                "don't share nodes. This is normal in complex workflows "
                "but means some branches don't feed into a final output — "
                "double-check that's intentional."
            ),
        )

    m = _RE_DYNAMIC_RENAME.match(trimmed)
    if m:
        node_id = int(m.group(1))
        mode = m.group(2)
        # group(3) is the trailing detail (e.g. "manual SQL rewrite needed").
        # We classify as missing_generator so the warning lands in "Manual
        # review needed" rather than the generic "Other" bucket.
        return ParsedWarning(
            kind="missing_generator",
            severity="review",
            raw=raw,
            node_id=node_id,
            tool="DynamicRename",
            title=(f"Node {node_id} (DynamicRename, {mode} mode) — needs manual rewrite"),
            detail=(
                "The rename map is data-driven, so a2d emitted a placeholder "
                "rather than a guess. Review the generated code for this "
                "node and supply the correct rename rules manually."
            ),
        )

    m = _RE_JOIN_NO_KEYS.match(trimmed)
    if m:
        node_id = int(m.group(1))
        return ParsedWarning(
            kind="missing_generator",
            severity="review",
            raw=raw,
            node_id=node_id,
            tool="Join",
            title=f"Node {node_id} (Join) — no join keys resolved",
            detail=(
                "a2d couldn't infer the join keys from the Alteryx workflow. "
                "The generated code uses `F.lit(True)` (a cross-join "
                "placeholder) — replace it with the correct join condition "
                "before running."
            ),
        )

    return ParsedWarning(
        kind="other",
        severity="review",
        raw=raw,
        title=trimmed,
        detail=(
            "a2d emitted this warning but the UI doesn't have a structured "
            "template for it yet. Use the original message for context."
        ),
    )


def parse_warnings(raws: Iterable[str]) -> list[ParsedWarning]:
    """Parse a list of raw warning strings, dropping empty entries."""
    return [parse_warning(s) for s in raws if s and s.strip()]


def categorize_warnings(parsed: Iterable[ParsedWarning]) -> CategorizedWarnings:
    """Group parsed warnings by user-facing bucket."""
    out = CategorizedWarnings()
    review_node_ids: set[int] = set()
    parsed_list = list(parsed)

    for w in parsed_list:
        if w.kind == "unsupported_tool":
            out.unsupported.append(w)
            if w.node_id is not None:
                review_node_ids.add(w.node_id)
        elif w.kind in ("missing_generator", "expression_fallback", "local_path"):
            out.review.append(w)
            if w.node_id is not None:
                review_node_ids.add(w.node_id)
        elif w.kind == "disconnected_components":
            out.graph.append(w)
        else:
            out.other.append(w)

    out.total = len(parsed_list)
    out.manual_review_node_count = len(review_node_ids)
    return out


def categorize_for_format(
    workflow_warnings: Iterable[str],
    format_warnings: Iterable[str],
) -> CategorizedWarnings:
    """Combine workflow-level + format-specific warnings and categorize."""
    return categorize_warnings(parse_warnings(list(workflow_warnings)) + parse_warnings(list(format_warnings)))


def categorize_across_all_formats(
    workflow_warnings: Iterable[str],
    format_warnings_lists: Iterable[Iterable[str]],
) -> CategorizedWarnings:
    """Aggregate warnings across workflow + every per-format list.

    Used by headline counts so they don't contradict the per-format tabs.
    Per-format expression fallbacks + missing-generator warnings + per-format
    unsupported entries live in ``formats[fmt].warnings``, not the workflow
    list. Reading only the workflow list for the headline counts is wrong.

    Deduplicates by ``(kind, node_id, generator, tool)`` so the same node
    appearing in three format warning lists counts once.
    """
    parsed: list[ParsedWarning] = list(parse_warnings(list(workflow_warnings)))
    for fmt_warnings in format_warnings_lists:
        parsed.extend(parse_warnings(list(fmt_warnings)))

    seen: set[tuple[str, int | None, str | None, str | None]] = set()
    deduped: list[ParsedWarning] = []
    for w in parsed:
        key = (w.kind, w.node_id, w.generator, w.tool)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(w)
    return categorize_warnings(deduped)


def nodes_in_broken_components(parsed: Iterable[ParsedWarning]) -> set[int]:
    """Return node ids in disconnected components that include unsupported nodes.

    These are the nodes that actually break the dataflow — used by the deploy
    status decision to escalate to ``cannot_deploy``.
    """
    parsed_list = list(parsed)
    components: list[tuple[int, ...]] = []
    for w in parsed_list:
        if w.kind == "disconnected_components" and w.components:
            components.extend(w.components)
    if not components:
        return set()

    unsupported_ids: set[int] = {
        w.node_id for w in parsed_list if w.kind == "unsupported_tool" and w.node_id is not None
    }
    broken: set[int] = set()
    for comp in components:
        if any(node_id in unsupported_ids for node_id in comp):
            broken.update(comp)
    return broken
