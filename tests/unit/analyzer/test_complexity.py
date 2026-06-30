"""Tests for the complexity analyzer module."""

from __future__ import annotations

from a2d.analyzer.complexity import ComplexityAnalyzer, ComplexityScore
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    BufferNode,
    CreatePointsNode,
    FilterNode,
    ReadNode,
    SpatialMatchNode,
)


def _make_dag(*nodes):
    dag = WorkflowDAG()
    for node in nodes:
        dag.add_node(node)
    return dag


class TestComplexityScoreToDict:
    def test_to_dict_contains_all_fields(self):
        score = ComplexityScore(
            total_score=42.5,
            level="Medium",
            node_count=10,
            edge_count=9,
            unique_tool_types=5,
            unsupported_count=2,
            expression_count=3,
            max_dag_depth=4,
            has_macro_refs=False,
            spatial_tool_count=1,
            detail={"node_score": 50.0},
        )
        d = score.to_dict()

        assert d["total_score"] == 42.5
        assert d["level"] == "Medium"
        assert d["node_count"] == 10
        assert d["edge_count"] == 9
        assert d["unique_tool_types"] == 5
        assert d["unsupported_count"] == 2
        assert d["expression_count"] == 3
        assert d["max_dag_depth"] == 4
        assert d["has_macro_refs"] is False
        assert d["spatial_tool_count"] == 1
        assert d["detail"] == {"node_score": 50.0}

    def test_to_dict_rounds_total_score(self):
        score = ComplexityScore(
            total_score=42.567,
            level="Medium",
            node_count=0,
            edge_count=0,
            unique_tool_types=0,
            unsupported_count=0,
            expression_count=0,
            max_dag_depth=0,
            has_macro_refs=False,
        )
        assert score.to_dict()["total_score"] == 42.6


class TestSpatialToolCount:
    def test_spatial_nodes_counted(self):
        analyzer = ComplexityAnalyzer()
        dag = _make_dag(
            ReadNode(node_id=1),
            SpatialMatchNode(node_id=2),
            BufferNode(node_id=3),
            CreatePointsNode(node_id=4),
        )
        result = analyzer.analyze(dag)

        assert result.spatial_tool_count == 3

    def test_no_spatial_nodes(self):
        analyzer = ComplexityAnalyzer()
        dag = _make_dag(
            ReadNode(node_id=1),
            FilterNode(node_id=2, expression="x > 0"),
        )
        result = analyzer.analyze(dag)

        assert result.spatial_tool_count == 0

    def test_spatial_nodes_increase_complexity(self):
        analyzer = ComplexityAnalyzer()

        dag_no_spatial = _make_dag(ReadNode(node_id=1))
        score_no_spatial = analyzer.analyze(dag_no_spatial)

        dag_with_spatial = _make_dag(
            ReadNode(node_id=1),
            SpatialMatchNode(node_id=2),
            BufferNode(node_id=3),
            CreatePointsNode(node_id=4),
        )
        score_with_spatial = analyzer.analyze(dag_with_spatial)

        assert score_with_spatial.total_score > score_no_spatial.total_score

    def test_empty_dag(self):
        analyzer = ComplexityAnalyzer()
        dag = WorkflowDAG()
        result = analyzer.analyze(dag)

        assert result.spatial_tool_count == 0
        assert result.total_score == 0.0
        assert result.level == "Low"
