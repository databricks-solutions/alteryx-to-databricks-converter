"""Workflow-level orchestration for LLM-assisted conversion.

Scans a parsed workflow's IR DAG for unsupported nodes, proposes a conversion
for each, and — when sample data (and optionally per-node golden outputs) are
supplied — verifies the proposals through the reference-executor gate. The
input frame to an unsupported node is obtained by running the reference
executor over the workflow: the unsupported node is skipped, but its
predecessor's output is available and becomes the candidate's sample input.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from a2d.config import ConversionConfig
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import UnsupportedNode
from a2d.llm.assist import AssistOutcome, LLMAssistedConverter
from a2d.llm.client import LLMClient
from a2d.llm.models import ConversionRequest

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger("a2d.llm.workflow")


@dataclass
class WorkflowAssistReport:
    """Aggregate of assist outcomes across one workflow."""

    workflow_name: str
    unsupported_total: int
    outcomes: list[AssistOutcome] = field(default_factory=list)

    @property
    def proposed(self) -> int:
        return sum(1 for o in self.outcomes if o.candidate is not None)

    @property
    def verified(self) -> int:
        return sum(1 for o in self.outcomes if o.accepted)

    @property
    def unverified(self) -> int:
        return sum(1 for o in self.outcomes if o.candidate is not None and o.verdict is not None and not o.accepted)


def scan_dag(
    dag: WorkflowDAG,
    workflow_name: str,
    *,
    client: LLMClient | None = None,
    source_data: dict[str | int, pd.DataFrame] | None = None,
    node_goldens: dict[int, pd.DataFrame] | None = None,
    max_candidates: int = 3,
) -> WorkflowAssistReport:
    """Propose (and verify where possible) conversions for unsupported nodes."""
    converter = LLMAssistedConverter(client=client)
    node_goldens = node_goldens or {}

    # Precompute per-node input frames from a single reference run (if we have data).
    input_frames = _compute_input_frames(dag, source_data) if source_data else {}

    unsupported = [n for n in dag.all_nodes() if isinstance(n, UnsupportedNode)]
    report = WorkflowAssistReport(workflow_name=workflow_name, unsupported_total=len(unsupported))

    for node in sorted(unsupported, key=lambda n: n.node_id):
        request = ConversionRequest(
            tool_type=node.original_tool_type or "Unknown",
            plugin_name=node.original_plugin_name,
            configuration=getattr(node, "original_configuration", {}) or {},
            annotation=node.annotation,
            node_id=node.node_id,
        )
        outcome = converter.assist(
            request,
            sample_input=input_frames.get(node.node_id),
            expected_output=node_goldens.get(node.node_id),
            max_candidates=max_candidates,
        )
        outcome.configuration = request.configuration
        report.outcomes.append(outcome)

    return report


def _compute_input_frames(
    dag: WorkflowDAG,
    source_data: dict[str | int, pd.DataFrame],
) -> dict[int, pd.DataFrame]:
    """Map each node id to the frame arriving on its single input, via reference run.

    Runs the pandas reference executor over the whole DAG; for every node with
    exactly one resolved upstream output we record that upstream frame as the
    node's input. Unsupported nodes are skipped by the executor but their
    predecessors' outputs remain available.
    """
    try:
        from a2d.verification.reference import ReferenceExecutor
    except ImportError:
        return {}

    executor = ReferenceExecutor(source_data=source_data)
    result = executor.execute(dag)

    frames: dict[int, pd.DataFrame] = {}
    for node in dag.all_nodes():
        preds = dag.get_predecessors(node.node_id)
        if len(preds) != 1:
            continue
        upstream = result.outputs.get(preds[0].node_id)
        if upstream is not None:
            frames[node.node_id] = upstream
    return frames


def scan_workflow_file(
    path,
    *,
    config: ConversionConfig | None = None,
    client: LLMClient | None = None,
    source_data: dict[str | int, pd.DataFrame] | None = None,
    node_goldens: dict[int, pd.DataFrame] | None = None,
) -> WorkflowAssistReport:
    """Parse a .yxmd/.yxmc file and scan it for assistable unsupported nodes."""
    from pathlib import Path

    from a2d.parser.workflow_parser import WorkflowParser
    from a2d.pipeline import ConversionPipeline

    path = Path(path)
    cfg = config or ConversionConfig()
    parsed = WorkflowParser().parse(path)
    dag = ConversionPipeline(cfg)._build_dag(parsed)
    return scan_dag(
        dag,
        path.stem,
        client=client,
        source_data=source_data,
        node_goldens=node_goldens,
    )
