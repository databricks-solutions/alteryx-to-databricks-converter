"""Build a ReviewSession from an IR DAG and a generated output.

The generators emit one notebook/script *cell* per node, each prefixed with a
``# Step <node_id>: ...`` marker (SQL uses ``-- Step <node_id>``). We run the
generator once and split its output on the cell separator, matching each cell to
its node by that marker — so the code shown per node is exactly what the
generator produced, with no parallel code path to drift.
"""

from __future__ import annotations

import re

from a2d.config import ConversionConfig, OutputFormat
from a2d.ir.graph import WorkflowDAG
from a2d.review.models import (
    ReviewEdge,
    ReviewNode,
    ReviewSession,
    node_review_status,
)

# Matches the per-node step marker emitted by every generator (# or -- prefix).
_STEP_RE = re.compile(r"^\s*(?:#|--)\s*Step\s+(\d+)\s*:", re.MULTILINE)

_GENERATORS = {
    OutputFormat.PYSPARK: "a2d.generators.pyspark:PySparkGenerator",
    OutputFormat.SQL: "a2d.generators.sql:SQLGenerator",
    OutputFormat.DLT: "a2d.generators.dlt:DLTGenerator",
    OutputFormat.LAKEFLOW: "a2d.generators.lakeflow:LakeflowGenerator",
}


def _load_generator(fmt: OutputFormat, config: ConversionConfig):
    module_name, cls_name = _GENERATORS[fmt].split(":")
    module = __import__(module_name, fromlist=[cls_name])
    return getattr(module, cls_name)(config)


def _cell_code_by_node(content: str) -> dict[int, str]:
    """Split generated content into per-node code keyed by node id.

    A cell owns everything from its ``Step <id>`` marker up to the next marker.
    Cells with no marker (header, imports, footer) are ignored.
    """
    matches = list(_STEP_RE.finditer(content))
    by_node: dict[int, str] = {}
    for i, m in enumerate(matches):
        node_id = int(m.group(1))
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        # Trim the trailing cell separator if present.
        cell = content[start:end].split("# COMMAND ----------")[0].rstrip()
        by_node[node_id] = cell
    return by_node


def build_review_session(
    dag: WorkflowDAG,
    workflow_name: str,
    *,
    output_format: OutputFormat = OutputFormat.PYSPARK,
    config: ConversionConfig | None = None,
) -> ReviewSession:
    """Assemble a review session pairing each node with its generated code."""
    cfg = config or ConversionConfig(output_format=output_format)
    generator = _load_generator(output_format, cfg)
    output = generator.generate(dag, workflow_name)

    # Concatenate all generated file contents; the step markers are unique per
    # node across the (usually single) generated file.
    content = "\n".join(f.content for f in output.files)
    code_by_node = _cell_code_by_node(content)

    # Per-node warnings: match generator warnings mentioning "node <id>".
    warnings_by_node: dict[int, list[str]] = {}
    for w in output.warnings:
        m = re.search(r"node\s+(\d+)", w)
        if m:
            warnings_by_node.setdefault(int(m.group(1)), []).append(w)

    session = ReviewSession(workflow_name=workflow_name, output_format=output_format.value)

    for node in dag.topological_order():
        node_warnings = warnings_by_node.get(node.node_id, [])
        tool_type = node.original_tool_type or type(node).__name__.replace("Node", "")
        session.nodes.append(
            ReviewNode(
                node_id=node.node_id,
                tool_type=tool_type,
                annotation=node.annotation,
                position=node.position,
                status=node_review_status(node, node_warnings),
                confidence=node.conversion_confidence,
                generated_code=code_by_node.get(node.node_id, ""),
                warnings=node_warnings,
                conversion_method=node.conversion_method,
            )
        )

    for src, tgt, info in dag.all_edges():
        session.edges.append(
            ReviewEdge(
                source_id=src,
                target_id=tgt,
                origin_anchor=info.origin_anchor,
                destination_anchor=info.destination_anchor,
            )
        )

    return session
