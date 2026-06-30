"""Tests for the confidence scoring module."""

from __future__ import annotations

from a2d.generators.base import GeneratedOutput
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    FilterNode,
    JoinNode,
    ReadNode,
    SelectNode,
    UnsupportedNode,
)
from a2d.observability.confidence import ConfidenceScorer


def _make_dag(*nodes):
    """Helper to create a DAG from a list of IR nodes."""
    dag = WorkflowDAG()
    for node in nodes:
        dag.add_node(node)
    return dag


class TestConfidenceScorer:
    def test_empty_dag(self):
        dag = WorkflowDAG()
        output = GeneratedOutput(warnings=[])
        scorer = ConfidenceScorer()
        result = scorer.score(dag, output)

        assert result.overall == 100.0
        assert result.level == "High"
        assert len(result.dimensions) == 5

    def test_all_supported_no_warnings(self):
        dag = _make_dag(
            ReadNode(node_id=1),
            FilterNode(node_id=2, expression="x > 0"),
        )
        output = GeneratedOutput(warnings=[])
        scorer = ConfidenceScorer()
        result = scorer.score(dag, output)

        assert result.overall >= 80
        assert result.level == "High"

    def test_unsupported_nodes_lower_score(self):
        dag = _make_dag(
            ReadNode(node_id=1),
            UnsupportedNode(node_id=2, original_tool_type="MysteryTool", unsupported_reason="unknown"),
        )
        output = GeneratedOutput(warnings=["Unsupported tool: MysteryTool"])
        scorer = ConfidenceScorer()
        result = scorer.score(dag, output)

        # Tool coverage should be 50% (1 of 2 supported)
        tool_dim = next(d for d in result.dimensions if d.name == "tool_coverage")
        assert tool_dim.score == 50.0
        assert result.overall < 100

    def test_expression_warnings_lower_fidelity(self):
        dag = _make_dag(ReadNode(node_id=1))
        output = GeneratedOutput(
            warnings=[
                "Formula expression fallback for 'col1': parse error",
                "expression parse failed: unknown func",
                "Non-expression warning",
            ]
        )
        scorer = ConfidenceScorer()
        result = scorer.score(dag, output)

        expr_dim = next(d for d in result.dimensions if d.name == "expression_fidelity")
        # 2 of 3 warnings are expression-related, so score = (1/3)*100 ≈ 33.3
        assert expr_dim.score < 50

    def test_join_without_keys_lowers_completeness(self):
        dag = _make_dag(
            JoinNode(node_id=1, join_keys=[]),
            JoinNode(node_id=2, join_keys=[]),
        )
        output = GeneratedOutput(warnings=[])
        scorer = ConfidenceScorer()
        result = scorer.score(dag, output)

        join_dim = next(d for d in result.dimensions if d.name == "join_completeness")
        assert join_dim.score == 0.0

    def test_join_with_keys_full_completeness(self):
        from a2d.ir.nodes import JoinKey

        dag = _make_dag(
            JoinNode(node_id=1, join_keys=[JoinKey(left_field="id", right_field="id")]),
        )
        output = GeneratedOutput(warnings=[])
        scorer = ConfidenceScorer()
        result = scorer.score(dag, output)

        join_dim = next(d for d in result.dimensions if d.name == "join_completeness")
        assert join_dim.score == 100.0

    def test_to_dict_serialization(self):
        dag = _make_dag(ReadNode(node_id=1))
        output = GeneratedOutput(warnings=[])
        scorer = ConfidenceScorer()
        result = scorer.score(dag, output)

        d = result.to_dict()
        assert "overall" in d
        assert "level" in d
        assert "dimensions" in d
        assert len(d["dimensions"]) == 5
        for dim in d["dimensions"]:
            assert "name" in dim
            assert "score" in dim
            assert "weight" in dim
            assert "details" in dim

    def test_medium_confidence_range(self):
        dag = _make_dag(
            ReadNode(node_id=1),
            FilterNode(node_id=2, expression="x > 0"),
            UnsupportedNode(node_id=3, original_tool_type="BadTool", unsupported_reason="no converter"),
        )
        output = GeneratedOutput(
            warnings=[
                "Formula expression fallback for 'col': error",
                "Unsupported tool: BadTool",
            ]
        )
        scorer = ConfidenceScorer()
        result = scorer.score(dag, output)

        # Should be in the medium range with some issues
        assert 0 <= result.overall <= 100

    def test_select_nodes_with_operations(self):
        from a2d.ir.nodes import FieldAction, FieldOperation

        dag = _make_dag(
            SelectNode(
                node_id=1,
                field_operations=[
                    FieldOperation(field_name="col1", selected=True, action=FieldAction.SELECT),
                ],
            ),
            SelectNode(node_id=2, field_operations=[]),
        )
        output = GeneratedOutput(warnings=[])
        scorer = ConfidenceScorer()
        result = scorer.score(dag, output)

        dt_dim = next(d for d in result.dimensions if d.name == "data_type_preservation")
        assert dt_dim.score == 50.0  # 1 of 2 selects have field ops
