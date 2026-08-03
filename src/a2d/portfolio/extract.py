"""Extract I/O artifacts, macros and sub-flow fingerprints from an IR DAG.

These are the raw signals the :class:`~a2d.portfolio.analyzer.PortfolioAnalyzer`
uses to link workflows together across the estate.
"""

from __future__ import annotations

import hashlib

from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    DynamicInputNode,
    DynamicOutputNode,
    IRNode,
    ReadNode,
    WriteNode,
)
from a2d.portfolio.models import WorkflowArtifacts

# A connected component smaller than this is too trivial to be a meaningful
# "duplicate sub-flow" (e.g. a lone Browse node), so we skip fingerprinting it.
_MIN_SUBFLOW_NODES = 3


def normalize_artifact(raw: str) -> str:
    """Normalize a file path or table name for cross-workflow matching.

    Lower-cases, strips whitespace/quotes, and unifies path separators so that
    ``C:\\Data\\Sales.csv`` and ``c:/data/sales.csv`` compare equal.
    """
    text = (raw or "").strip().strip("'\"").replace("\\", "/").lower()
    # Collapse a trailing slash so "dir/" == "dir".
    if len(text) > 1 and text.endswith("/"):
        text = text[:-1]
    return text


def _read_artifact(node: ReadNode) -> str:
    """The artifact identity a ReadNode consumes (table preferred over path)."""
    return node.table_name or node.file_path or node.connection_string


def _write_artifact(node: WriteNode) -> str:
    """The artifact identity a WriteNode produces."""
    return node.table_name or node.file_path or node.connection_string


def extract_artifacts(
    workflow_name: str,
    file_path: str,
    dag: WorkflowDAG,
    macro_references: list[str],
) -> WorkflowArtifacts:
    """Pull reads/writes/macros/sub-flow fingerprints out of a workflow DAG."""
    reads: set[str] = set()
    writes: set[str] = set()

    for node in dag.all_nodes():
        if isinstance(node, ReadNode):
            artifact = normalize_artifact(_read_artifact(node))
            if artifact:
                reads.add(artifact)
        elif isinstance(node, DynamicInputNode):
            artifact = normalize_artifact(node.file_path_pattern or node.template_connection)
            if artifact:
                reads.add(artifact)
        elif isinstance(node, WriteNode):
            artifact = normalize_artifact(_write_artifact(node))
            if artifact:
                writes.add(artifact)
        elif isinstance(node, DynamicOutputNode):
            artifact = normalize_artifact(node.file_path_expression)
            if artifact:
                writes.add(artifact)

    macros = {normalize_artifact(m) for m in macro_references if m}
    macros.discard("")

    subflow_fingerprints = _fingerprint_subflows(dag)

    return WorkflowArtifacts(
        file_path=file_path,
        workflow_name=workflow_name,
        reads=reads,
        writes=writes,
        macros=macros,
        subflow_fingerprints=subflow_fingerprints,
    )


def _fingerprint_subflows(dag: WorkflowDAG) -> dict[str, str]:
    """Fingerprint each non-trivial connected component of the DAG.

    The fingerprint is a hash of the *sorted* tool-type multiset of the
    component. Sorting makes it order-insensitive so the same set of tools
    laid out differently still matches — a deliberate choice to catch
    copy-paste sub-flows even when node IDs and canvas positions differ.
    """
    fingerprints: dict[str, str] = {}
    for component in dag.get_connected_components():
        if len(component) < _MIN_SUBFLOW_NODES:
            continue
        tool_types = sorted(_tool_type(dag.get_node(nid)) for nid in component)
        digest = hashlib.sha1("|".join(tool_types).encode("utf-8")).hexdigest()[:12]
        description = _summarize_tool_types(tool_types)
        fingerprints[digest] = description
    return fingerprints


def _tool_type(node: IRNode) -> str:
    """Human-readable tool type for a node (mirrors coverage/complexity)."""
    return node.original_tool_type or type(node).__name__.replace("Node", "")


def _summarize_tool_types(tool_types: list[str]) -> str:
    """A compact 'Tool xN + Tool ...' description of a component's tools."""
    counts: dict[str, int] = {}
    for t in tool_types:
        counts[t] = counts.get(t, 0) + 1
    parts = [(f"{name} x{n}" if n > 1 else name) for name, n in sorted(counts.items())]
    return ", ".join(parts)
