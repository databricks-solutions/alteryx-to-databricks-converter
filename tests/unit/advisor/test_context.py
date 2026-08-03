"""Tests for the advisory migration-context collector."""

from __future__ import annotations

from a2d.advisor.context import LOW_CONFIDENCE, build_migration_context
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import FilterNode, ReadNode, UnsupportedNode, WriteNode


def _dag_with_unsupported() -> WorkflowDAG:
    dag = WorkflowDAG()
    dag.add_node(ReadNode(node_id=1, original_tool_type="Input"))
    dag.add_node(
        UnsupportedNode(
            node_id=2,
            original_tool_type="Message",
            original_configuration={"MessageText": "hello"},
            unsupported_reason="No converter for tool type: Message",
        )
    )
    dag.add_node(WriteNode(node_id=3, original_tool_type="Output"))
    dag.add_edge(1, 2)
    dag.add_edge(2, 3)
    return dag


def _plain_dag() -> WorkflowDAG:
    dag = WorkflowDAG()
    dag.add_node(ReadNode(node_id=1, original_tool_type="Input"))
    dag.add_node(FilterNode(node_id=2, original_tool_type="Filter", expression="[x] > 0"))
    dag.add_edge(1, 2)
    return dag


class TestGapCollection:
    def test_unsupported_node_becomes_blocking_gap(self):
        ctx = build_migration_context(_dag_with_unsupported(), workflow_name="wf", output_format="pyspark")
        gaps = [g for g in ctx.gaps if g.kind == "unsupported_tool"]
        assert len(gaps) == 1
        assert gaps[0].node_id == 2
        assert gaps[0].tool_type == "Message"
        assert ctx.blocking_gaps == gaps

    def test_original_configuration_is_carried_for_suggestions(self):
        """The original config is the richest signal for a suggestion."""
        ctx = build_migration_context(_dag_with_unsupported(), workflow_name="wf", output_format="pyspark")
        gap = next(g for g in ctx.gaps if g.node_id == 2)
        assert gap.original_configuration == {"MessageText": "hello"}
        assert "No converter" in gap.unsupported_reason

    def test_no_gaps_for_fully_supported_workflow(self):
        ctx = build_migration_context(_plain_dag(), workflow_name="wf", output_format="pyspark")
        assert ctx.gaps == []
        assert ctx.has_gaps is False

    def test_todo_markers_in_generated_code_become_gaps(self):
        ctx = build_migration_context(
            _plain_dag(),
            workflow_name="wf",
            output_format="pyspark",
            generated_code="df = x\n# TODO: replace with a geocoding UDF\n",
        )
        todos = [g for g in ctx.gaps if g.kind == "todo"]
        assert len(todos) == 1
        assert "geocoding" in todos[0].summary

    def test_sql_comment_todo_is_detected(self):
        ctx = build_migration_context(
            _plain_dag(),
            workflow_name="wf",
            output_format="sql",
            generated_code="-- TODO: add join condition\nSELECT 1",
        )
        assert [g.summary for g in ctx.gaps if g.kind == "todo"] == ["add join condition"]

    def test_review_warning_becomes_gap(self):
        ctx = build_migration_context(
            _plain_dag(),
            workflow_name="wf",
            output_format="pyspark",
            format_warnings=["No PySpark generator for CrosstabNode (node 7)"],
        )
        assert any(g.kind == "review_warning" for g in ctx.gaps)

    def test_unsupported_warning_not_duplicated_for_known_node(self):
        """A warning about node 2 must not double-count the UnsupportedNode."""
        ctx = build_migration_context(
            _dag_with_unsupported(),
            workflow_name="wf",
            output_format="pyspark",
            format_warnings=["Unsupported node 2: No converter for tool type: Message"],
        )
        assert len([g for g in ctx.gaps if g.node_id == 2]) == 1


class TestDecisions:
    def test_low_confidence_node_is_explained(self):
        dag = _plain_dag()
        dag.get_node(2).conversion_confidence = LOW_CONFIDENCE - 0.3
        ctx = build_migration_context(dag, workflow_name="wf", output_format="pyspark")
        assert [d.node_id for d in ctx.decisions] == [2]

    def test_non_default_method_is_explained(self):
        dag = _plain_dag()
        dag.get_node(2).conversion_method = "template"
        ctx = build_migration_context(dag, workflow_name="wf", output_format="pyspark")
        assert [d.node_id for d in ctx.decisions] == [2]

    def test_high_confidence_deterministic_node_is_not_noise(self):
        ctx = build_migration_context(_plain_dag(), workflow_name="wf", output_format="pyspark")
        assert ctx.decisions == []


class TestSerialization:
    def test_to_dict_round_trips_summary(self):
        ctx = build_migration_context(
            _dag_with_unsupported(), workflow_name="wf", output_format="pyspark", coverage=66.6
        )
        data = ctx.to_dict()
        assert data["workflow_name"] == "wf"
        assert data["coverage"] == 66.6
        assert data["summary"]["total_gaps"] == len(ctx.gaps)
        assert data["summary"]["blocking_gaps"] == 1

    def test_deploy_status_is_derived(self):
        ctx = build_migration_context(
            _plain_dag(), workflow_name="wf", output_format="pyspark", coverage=100.0, confidence=95.0
        )
        assert ctx.deploy_status in ("ready", "needs_review", "cannot_deploy")
