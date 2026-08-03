"""Tests for the cost & performance advisor."""

from __future__ import annotations

from a2d.advisor import CostPerformanceAdvisor
from a2d.config import ConversionConfig
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    BufferNode,
    FilterNode,
    JoinNode,
    PredictiveModelNode,
    ReadNode,
    SummarizeNode,
    WriteNode,
)


def _linear_dag(n: int) -> WorkflowDAG:
    """A simple Read -> Filter x(n-2) -> Write chain."""
    dag = WorkflowDAG()
    dag.add_node(ReadNode(node_id=0, original_tool_type="Input"))
    prev = 0
    for i in range(1, n - 1):
        dag.add_node(FilterNode(node_id=i, original_tool_type="Filter", expression="[x] > 0"))
        dag.add_edge(prev, i)
        prev = i
    dag.add_node(WriteNode(node_id=n - 1, original_tool_type="Output"))
    dag.add_edge(prev, n - 1)
    return dag


class TestClusterSizing:
    def test_small_linear_workflow_is_single_node(self):
        dag = _linear_dag(4)
        rep = CostPerformanceAdvisor().analyze(dag, workflow_name="tiny")
        assert rep.cluster.tier == "single-node"
        assert rep.cluster.workers == 0
        assert rep.cluster.photon_recommended is False

    def test_shuffle_ops_recommend_photon_and_workers(self):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, original_tool_type="Input"))
        dag.add_node(ReadNode(node_id=2, original_tool_type="Input"))
        dag.add_node(JoinNode(node_id=3, original_tool_type="Join"))
        dag.add_node(SummarizeNode(node_id=4, original_tool_type="Summarize"))
        dag.add_edge(1, 3)
        dag.add_edge(2, 3)
        dag.add_edge(3, 4)
        rep = CostPerformanceAdvisor().analyze(dag, workflow_name="joins")
        assert rep.cluster.workers >= 2
        assert rep.cluster.photon_recommended is True

    def test_ml_ops_size_up(self):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, original_tool_type="Input"))
        for i in range(2, 6):
            dag.add_node(PredictiveModelNode(node_id=i, original_tool_type="ForestModel"))
            dag.add_edge(i - 1, i)
        rep = CostPerformanceAdvisor().analyze(dag, workflow_name="ml")
        assert rep.cluster.tier in ("medium", "large")
        assert any("ML" in r or "predictive" in r for r in rep.cluster.rationale)

    def test_spatial_ops_size_up(self):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, original_tool_type="Input"))
        for i in range(2, 7):
            dag.add_node(BufferNode(node_id=i, original_tool_type="Buffer"))
            dag.add_edge(i - 1, i)
        rep = CostPerformanceAdvisor().analyze(dag, workflow_name="spatial")
        assert rep.cluster.tier in ("medium", "large")

    def test_node_type_id_follows_cloud(self):
        dag = _linear_dag(4)
        rep = CostPerformanceAdvisor().analyze(dag, ConversionConfig(cloud="azure"), workflow_name="w")
        assert rep.cluster.node_type_id == "Standard_DS3_v2"


class TestReport:
    def test_report_includes_hints(self):
        # Two literal-like reads into a join → broadcast hint.
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, original_tool_type="Input"))
        dag.add_node(ReadNode(node_id=2, original_tool_type="Input"))
        dag.add_node(JoinNode(node_id=3, original_tool_type="Join"))
        dag.add_edge(1, 3)
        dag.add_edge(2, 3)
        rep = CostPerformanceAdvisor().analyze(dag, workflow_name="j")
        assert rep.node_count == 3
        assert rep.hints  # at least one broadcast hint

    def test_to_dict_is_serializable(self):
        import json

        dag = _linear_dag(5)
        rep = CostPerformanceAdvisor().analyze(dag, workflow_name="w")
        doc = json.loads(json.dumps(rep.to_dict()))
        assert doc["cluster"]["tier"]
        assert "summary" in doc

    def test_empty_dag(self):
        rep = CostPerformanceAdvisor().analyze(WorkflowDAG(), workflow_name="empty")
        assert rep.cluster.tier == "single-node"
        assert rep.node_count == 0
