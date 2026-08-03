"""Tests for the verification runner and Spark-backend availability guard."""

from __future__ import annotations

from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from a2d.verification.runner import verify_workflow
from a2d.verification.spark_backend import SparkBackend, spark_available

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "workflows"
JOIN_SUMMARIZE = FIXTURES / "join_and_summarize.yxmd"


class TestSparkAvailability:
    def test_spark_available_returns_tuple(self):
        ok, reason = spark_available()
        assert isinstance(ok, bool)
        assert isinstance(reason, str) and reason

    def test_spark_backend_degrades_when_unavailable(self):
        # Whatever the environment, execute() must never raise — it either runs
        # (JVM present) or returns available=False with a reason.
        dag_src = pd.DataFrame({"a": [1]})
        from a2d.ir.graph import WorkflowDAG
        from a2d.ir.nodes import ReadNode

        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, table_name="t"))
        res = SparkBackend({"t": dag_src}).execute(dag)
        if not res.available:
            assert res.reason
            assert res.outputs == {}


class TestRunnerModes:
    def test_reference_only_is_inconclusive(self):
        res = verify_workflow(JOIN_SUMMARIZE, source_data={}, use_spark=False)
        assert res.status == "inconclusive"
        assert res.mode == "reference_only"
        assert res.sink_node_id is not None

    def test_golden_pass(self):
        expected = pd.DataFrame({"Region": ["East", "West"], "Total_Amount": [551.5, 200.0], "Order_Count": [3, 1]})
        res = verify_workflow(JOIN_SUMMARIZE, source_data={}, expected_output=expected, use_spark=False)
        assert res.status == "pass"
        assert res.mode == "golden"
        assert res.parity is not None and res.parity.passed

    def test_golden_fail_reports_mismatch(self):
        expected = pd.DataFrame({"Region": ["East", "West"], "Total_Amount": [999.0, 200.0], "Order_Count": [3, 1]})
        res = verify_workflow(JOIN_SUMMARIZE, source_data={}, expected_output=expected, use_spark=False)
        assert res.status == "fail"
        assert res.parity is not None and not res.parity.passed

    def test_missing_workflow_is_error(self):
        res = verify_workflow(Path("does_not_exist.yxmd"), source_data={}, use_spark=False)
        assert res.status == "error"
        assert res.error

    def test_to_dict_serializable(self):
        res = verify_workflow(JOIN_SUMMARIZE, source_data={}, use_spark=False)
        d = res.to_dict()
        assert d["workflow"] == "join_and_summarize"
        assert "status" in d and "parity" in d


class TestPartialCoverage:
    def test_unsupported_node_downgrades_pass_to_inconclusive(self):
        # A workflow with an unsupported node can never be a clean golden pass.
        from a2d.ir.graph import WorkflowDAG
        from a2d.ir.nodes import ReadNode, TileNode

        # Build a tiny DAG with an unsupported TileNode after a source, run the
        # reference executor directly to confirm the skip is recorded.
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, table_name="t"))
        dag.add_node(TileNode(node_id=2, tile_count=4, tile_field="v"))
        dag.add_edge(1, 2)
        from a2d.verification.reference import ReferenceExecutor

        res = ReferenceExecutor({"t": pd.DataFrame({"v": [1, 2, 3]})}).execute(dag)
        assert not res.fully_supported
        assert res.skipped[0][0] == 2
