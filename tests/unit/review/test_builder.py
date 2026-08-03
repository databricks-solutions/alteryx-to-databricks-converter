"""Tests for building a review session from an IR DAG."""

from __future__ import annotations

from pathlib import Path

import pytest

from a2d.config import ConversionConfig, OutputFormat
from a2d.parser.workflow_parser import WorkflowParser
from a2d.pipeline import ConversionPipeline
from a2d.review.builder import _cell_code_by_node, build_review_session

WORKFLOWS = Path(__file__).parent.parent.parent / "fixtures" / "workflows"


def _dag(path):
    parsed = WorkflowParser().parse(path)
    return ConversionPipeline(ConversionConfig())._build_dag(parsed), parsed


class TestCellSplitting:
    def test_splits_by_step_marker(self):
        content = (
            "# header\n\n# COMMAND ----------\n\n# Step 1: Read\ndf_1 = ...\n"
            "\n# COMMAND ----------\n\n# Step 2: Filter\ndf_2 = ...\n"
        )
        by_node = _cell_code_by_node(content)
        assert set(by_node) == {1, 2}
        assert "df_1" in by_node[1]
        assert "df_2" in by_node[2]

    def test_sql_double_dash_marker(self):
        content = "-- Step 5: Select\nSELECT * FROM t\n"
        by_node = _cell_code_by_node(content)
        assert 5 in by_node


class TestBuildReviewSession:
    def test_all_nodes_have_code(self):
        dag, _ = _dag(WORKFLOWS / "join_and_summarize.yxmd")
        session = build_review_session(dag, "join_and_summarize", output_format=OutputFormat.PYSPARK)
        assert session.total == dag.node_count
        assert session.edges  # has connections
        for node in session.nodes:
            assert node.generated_code.strip(), f"node {node.node_id} has no code"

    def test_unsupported_node_flagged_cannot_convert(self):
        dag, _ = _dag(WORKFLOWS / "message_passthrough.yxmd")
        session = build_review_session(dag, "message", output_format=OutputFormat.PYSPARK)
        statuses = {n.node_id: n.status for n in session.nodes}
        assert statuses[2] == "cannot_convert"  # the Message node
        assert not session.is_complete

    @pytest.mark.parametrize("fmt", [OutputFormat.PYSPARK, OutputFormat.SQL])
    def test_works_across_formats(self, fmt):
        dag, _ = _dag(WORKFLOWS / "simple_filter.yxmd")
        session = build_review_session(dag, "simple_filter", output_format=fmt)
        assert session.output_format == fmt.value
        assert session.total == dag.node_count

    def test_edges_carry_anchors(self):
        dag, _ = _dag(WORKFLOWS / "simple_filter.yxmd")
        session = build_review_session(dag, "simple_filter")
        assert all(e.origin_anchor and e.destination_anchor for e in session.edges)
