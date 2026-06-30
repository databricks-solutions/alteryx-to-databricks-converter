"""Tests for the Lakeflow Designer SQL generator."""

from __future__ import annotations

import json

import pytest

from a2d.config import ConversionConfig, OutputFormat
from a2d.generators.lakeflow import LakeflowGenerator
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    AggAction,
    AggregationField,
    AutoFieldNode,
    CloudStorageNode,
    DynamicInputNode,
    FilterNode,
    FormulaField,
    FormulaNode,
    JoinKey,
    JoinNode,
    ReadNode,
    SortField,
    SortNode,
    SummarizeNode,
    UnionNode,
    UnsupportedNode,
    WriteNode,
)


@pytest.fixture
def config() -> ConversionConfig:
    return ConversionConfig(output_format=OutputFormat.LAKEFLOW)


@pytest.fixture
def generator(config: ConversionConfig) -> LakeflowGenerator:
    return LakeflowGenerator(config)


class TestLakeflowReadNode:
    def test_file_read_generates_streaming_table(self, generator: LakeflowGenerator):
        """File-based ReadNode should produce CREATE OR REFRESH STREAMING TABLE."""
        node = ReadNode(
            node_id=1,
            original_tool_type="Input Data",
            file_path="/data/input.csv",
            file_format="csv",
        )
        dag = WorkflowDAG()
        dag.add_node(node)

        output = generator.generate(dag, "test_lakeflow")
        content = output.files[0].content

        assert output.files[0].filename == "test_lakeflow_lakeflow.sql"
        assert output.files[0].file_type == "sql"
        assert "CREATE OR REFRESH STREAMING TABLE" in content
        assert "csv.`/data/input.csv`" in content
        assert "WITH" not in content  # no CTE wrapper

    def test_db_read_generates_materialized_view(self, generator: LakeflowGenerator):
        """Database ReadNode should produce MATERIALIZED VIEW, not STREAMING TABLE."""
        node = ReadNode(
            node_id=1,
            original_tool_type="Input Data",
            source_type="database",
            table_name="catalog.schema.customers",
        )
        dag = WorkflowDAG()
        dag.add_node(node)

        output = generator.generate(dag, "test_lakeflow")
        content = output.files[0].content

        assert "CREATE OR REFRESH MATERIALIZED VIEW" in content
        assert "STREAMING TABLE" not in content
        assert "catalog.schema.customers" in content

    def test_cloud_storage_generates_streaming_table(self, generator: LakeflowGenerator):
        """CloudStorageNode input should produce STREAMING TABLE."""
        node = CloudStorageNode(
            node_id=1,
            original_tool_type="Cloud Storage",
            provider="s3",
            direction="input",
            bucket_or_container="my-bucket",
            path="data/input.csv",
            file_format="csv",
        )
        dag = WorkflowDAG()
        dag.add_node(node)

        output = generator.generate(dag, "test_lakeflow")
        content = output.files[0].content

        assert "CREATE OR REFRESH STREAMING TABLE" in content


class TestLakeflowFilterNode:
    def test_filter_generates_where_with_live_prefix(self, generator: LakeflowGenerator):
        """FilterNode should reference upstream via LIVE. prefix."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        filt = FilterNode(node_id=2, original_tool_type="Filter", expression="[Age] > 25")

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(filt)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content

        assert "WHERE" in content
        assert "LIVE." in content
        assert "CREATE OR REFRESH MATERIALIZED VIEW step_2_filter" in content

    def test_filter_with_empty_expression(self, generator: LakeflowGenerator):
        """FilterNode with empty expression should emit a warning."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        filt = FilterNode(node_id=2, original_tool_type="Filter", expression="")

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(filt)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        assert any("no expression" in w.lower() or "expression not found" in w.lower() for w in output.warnings)


class TestLakeflowJoinNode:
    def test_join_with_live_prefix(self, generator: LakeflowGenerator):
        """JoinNode should reference both sides via LIVE. prefix."""
        left = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/left.csv", file_format="csv")
        right = ReadNode(node_id=2, original_tool_type="Input Data", file_path="/right.csv", file_format="csv")
        join = JoinNode(
            node_id=3,
            original_tool_type="Join",
            join_keys=[JoinKey(left_field="id", right_field="id")],
            join_type="inner",
        )

        dag = WorkflowDAG()
        dag.add_node(left)
        dag.add_node(right)
        dag.add_node(join)
        dag.add_edge(1, 3, destination_anchor="Left")
        dag.add_edge(2, 3, destination_anchor="Right")

        output = generator.generate(dag)
        content = output.files[0].content

        assert "JOIN" in content
        assert "ON" in content
        assert "LIVE." in content
        # Both sides should have LIVE. prefix
        assert content.count("LIVE.") >= 2

    def test_join_keys_present(self, generator: LakeflowGenerator):
        """Join ON clause should contain the key fields."""
        left = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/left.csv", file_format="csv")
        right = ReadNode(node_id=2, original_tool_type="Input Data", file_path="/right.csv", file_format="csv")
        join = JoinNode(
            node_id=3,
            original_tool_type="Join",
            join_keys=[JoinKey(left_field="customer_id", right_field="cust_id")],
            join_type="left",
        )

        dag = WorkflowDAG()
        dag.add_node(left)
        dag.add_node(right)
        dag.add_node(join)
        dag.add_edge(1, 3, destination_anchor="Left")
        dag.add_edge(2, 3, destination_anchor="Right")

        output = generator.generate(dag)
        content = output.files[0].content

        assert "`customer_id`" in content
        assert "`cust_id`" in content
        assert "LEFT JOIN" in content


class TestLakeflowSummarizeNode:
    def test_summarize_generates_group_by(self, generator: LakeflowGenerator):
        """SummarizeNode should produce GROUP BY in a MATERIALIZED VIEW."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        summ = SummarizeNode(
            node_id=2,
            original_tool_type="Summarize",
            aggregations=[
                AggregationField(field_name="Dept", action=AggAction.GROUP_BY),
                AggregationField(field_name="Salary", action=AggAction.SUM, output_field_name="Total"),
            ],
        )

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(summ)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content

        assert "GROUP BY" in content
        assert "SUM(" in content
        assert "`Total`" in content
        assert "CREATE OR REFRESH MATERIALIZED VIEW" in content


class TestLakeflowFormulaNode:
    def test_formula_generates_computed_columns(self, generator: LakeflowGenerator):
        """FormulaNode should produce computed columns in a MATERIALIZED VIEW."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        formula = FormulaNode(
            node_id=2,
            original_tool_type="Formula",
            formulas=[FormulaField(output_field="FullName", expression="[First] + ' ' + [Last]")],
        )

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(formula)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content

        assert "`FullName`" in content
        assert "CREATE OR REFRESH MATERIALIZED VIEW" in content


class TestLakeflowFormat:
    def test_lakeflow_header(self, generator: LakeflowGenerator):
        """Output should have Lakeflow-specific header."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        dag = WorkflowDAG()
        dag.add_node(read)

        output = generator.generate(dag, "my_workflow")
        content = output.files[0].content

        assert "-- Migrated from: my_workflow.yxmd" in content
        assert "-- Generated by: a2d v" in content
        assert "-- Format: Lakeflow Declarative Pipelines (LDP) SQL" in content
        assert "-- Next steps --" in content

    def test_no_with_clause(self, generator: LakeflowGenerator):
        """Lakeflow output should NOT contain WITH clause."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        filt = FilterNode(node_id=2, original_tool_type="Filter", expression="[Age] > 25")

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(filt)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content

        # Should not have CTE-style WITH
        lines = [line.strip() for line in content.split("\n") if line.strip() and not line.strip().startswith("--")]
        assert not any(line.startswith("WITH ") for line in lines)

    def test_individual_create_statements(self, generator: LakeflowGenerator):
        """Each node should have its own CREATE OR REFRESH statement."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        filt = FilterNode(node_id=2, original_tool_type="Filter", expression="[Age] > 25")

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(filt)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content

        create_count = content.count("CREATE OR REFRESH")
        assert create_count == 2  # one for read, one for filter

    def test_pipeline_json_generated(self, generator: LakeflowGenerator):
        """Generator should produce a companion pipeline JSON file."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        dag = WorkflowDAG()
        dag.add_node(read)

        output = generator.generate(dag, "my_pipeline")

        assert len(output.files) == 2
        json_file = next(f for f in output.files if f.file_type == "json")
        assert json_file.filename == "my_pipeline_lakeflow_pipeline.json"

        data = json.loads(json_file.content)
        assert data["name"] == "a2d_my_pipeline_lakeflow"
        assert data["catalog"] == "main"
        assert data["target"] == "default"
        assert data["channel"] == "CURRENT"
        assert data["development"] is True


class TestLakeflowPassthrough:
    def test_autofield_forwards_upstream_view(self, generator: LakeflowGenerator):
        """AutoFieldNode should forward the upstream view name (no new view)."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        auto = AutoFieldNode(node_id=2, original_tool_type="AutoField")
        write = WriteNode(node_id=3, original_tool_type="Output Data", file_path="/out.csv")

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(auto)
        dag.add_node(write)
        dag.add_edge(1, 2)
        dag.add_edge(2, 3)

        output = generator.generate(dag)
        content = output.files[0].content

        # AutoField should NOT create its own view
        assert "step_2_autofield" not in content
        # WriteNode should reference the read node's view via LIVE.
        assert "LIVE.step_1_input_data" in content


class TestLakeflowUnsupported:
    def test_unsupported_node_generates_placeholder(self, generator: LakeflowGenerator):
        """UnsupportedNode should produce a placeholder view with UNSUPPORTED comment."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        unsup = UnsupportedNode(
            node_id=2,
            original_tool_type="CustomTool",
            unsupported_reason="No converter available",
        )

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(unsup)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content

        assert "UNSUPPORTED" in content
        assert output.stats["unsupported_nodes"] == 1
        assert output.stats["supported_nodes"] == 1


class TestLakeflowFilterFanOut:
    def test_filter_true_false_branches(self, generator: LakeflowGenerator):
        """Filter with both True and False branches should produce two views."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        filt = FilterNode(node_id=2, original_tool_type="Filter", expression="[Age] > 25")
        out_true = WriteNode(node_id=3, original_tool_type="Output Data", file_path="/true.csv")
        out_false = WriteNode(node_id=4, original_tool_type="Output Data", file_path="/false.csv")

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(filt)
        dag.add_node(out_true)
        dag.add_node(out_false)
        dag.add_edge(1, 2)
        dag.add_edge(2, 3, origin_anchor="True")
        dag.add_edge(2, 4, origin_anchor="False")

        output = generator.generate(dag)
        content = output.files[0].content

        # Should have True and False views
        assert "step_2_filter_true" in content
        assert "step_2_filter_false" in content
        assert "NOT (" in content  # False branch negates the expression

        # Downstream nodes should reference the correct branch
        assert "LIVE.step_2_filter_true" in content
        assert "LIVE.step_2_filter_false" in content


class TestLakeflowEdgeCases:
    def test_empty_dag(self, generator: LakeflowGenerator):
        """Empty DAG should produce header-only SQL."""
        dag = WorkflowDAG()
        output = generator.generate(dag, "empty")
        content = output.files[0].content

        assert "-- Migrated from: empty.yxmd" in content
        assert output.stats["total_nodes"] == 0

    def test_multiple_sources_with_join(self, generator: LakeflowGenerator):
        """Multiple ReadNodes feeding into a Join should all have LIVE. prefix."""
        left = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/left.csv", file_format="csv")
        right = ReadNode(node_id=2, original_tool_type="Input Data", file_path="/right.csv", file_format="csv")
        join = JoinNode(
            node_id=3,
            original_tool_type="Join",
            join_keys=[JoinKey(left_field="id", right_field="id")],
            join_type="inner",
        )
        write = WriteNode(node_id=4, original_tool_type="Output Data", file_path="/out.csv")

        dag = WorkflowDAG()
        dag.add_node(left)
        dag.add_node(right)
        dag.add_node(join)
        dag.add_node(write)
        dag.add_edge(1, 3, destination_anchor="Left")
        dag.add_edge(2, 3, destination_anchor="Right")
        dag.add_edge(3, 4)

        output = generator.generate(dag)
        content = output.files[0].content

        # 4 CREATE statements (2 reads + 1 join + 1 write)
        assert content.count("CREATE OR REFRESH") == 4

    def test_union_with_live_prefix(self, generator: LakeflowGenerator):
        """UnionNode should reference all inputs via LIVE. prefix."""
        src1 = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/a.csv", file_format="csv")
        src2 = ReadNode(node_id=2, original_tool_type="Input Data", file_path="/b.csv", file_format="csv")
        union = UnionNode(node_id=3, original_tool_type="Union")

        dag = WorkflowDAG()
        dag.add_node(src1)
        dag.add_node(src2)
        dag.add_node(union)
        dag.add_edge(1, 3, destination_anchor="Input")
        dag.add_edge(2, 3, destination_anchor="Input2")

        output = generator.generate(dag)
        content = output.files[0].content

        assert "UNION ALL" in content
        # Both source views should be prefixed with LIVE.
        assert "LIVE.step_1_input_data" in content
        assert "LIVE.step_2_input_data" in content


class TestLakeflowStats:
    def test_stats_include_view_count(self, generator: LakeflowGenerator):
        """Stats should include total_views field."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        filt = FilterNode(node_id=2, original_tool_type="Filter", expression="[Age] > 25")

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(filt)
        dag.add_edge(1, 2)

        output = generator.generate(dag)

        assert output.stats["total_nodes"] == 2
        assert output.stats["total_views"] == 2
        assert output.stats["supported_nodes"] == 2
        assert output.stats["unsupported_nodes"] == 0


class TestLakeflowDynamicInput:
    def test_dynamic_input_generates_streaming_table(self, generator: LakeflowGenerator):
        """DynamicInputNode should produce STREAMING TABLE."""
        node = DynamicInputNode(
            node_id=1,
            original_tool_type="Dynamic Input",
            file_path_pattern="*.csv",
            file_format="csv",
        )
        dag = WorkflowDAG()
        dag.add_node(node)

        output = generator.generate(dag, "test")
        content = output.files[0].content

        assert "CREATE OR REFRESH STREAMING TABLE" in content


class TestLakeflowSortNode:
    def test_sort_generates_order_by(self, generator: LakeflowGenerator):
        """SortNode should produce ORDER BY in a MATERIALIZED VIEW."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        sort = SortNode(
            node_id=2,
            original_tool_type="Sort",
            sort_fields=[
                SortField(field_name="Name", ascending=True),
                SortField(field_name="Age", ascending=False),
            ],
        )

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(sort)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content

        assert "ORDER BY" in content
        assert "`Name` ASC" in content
        assert "`Age` DESC" in content
        assert "CREATE OR REFRESH MATERIALIZED VIEW" in content
        assert "LIVE." in content


class TestLakeflowFilterSingleBranch:
    def test_filter_true_only(self, generator: LakeflowGenerator):
        """Filter with only True branch should produce single view (no fan-out)."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        filt = FilterNode(node_id=2, original_tool_type="Filter", expression="[Age] > 25")
        out = WriteNode(node_id=3, original_tool_type="Output Data", file_path="/out.csv")

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(filt)
        dag.add_node(out)
        dag.add_edge(1, 2)
        dag.add_edge(2, 3, origin_anchor="True")

        output = generator.generate(dag)
        content = output.files[0].content

        # Single branch: no fan-out, just a normal filter view
        assert "step_2_filter_true" not in content
        assert "step_2_filter_false" not in content
        assert "WHERE" in content
        assert "NOT (" not in content

    def test_filter_false_only(self, generator: LakeflowGenerator):
        """Filter with only False branch should produce single view (no fan-out)."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        filt = FilterNode(node_id=2, original_tool_type="Filter", expression="[Age] > 25")
        out = WriteNode(node_id=3, original_tool_type="Output Data", file_path="/out.csv")

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(filt)
        dag.add_node(out)
        dag.add_edge(1, 2)
        dag.add_edge(2, 3, origin_anchor="False")

        output = generator.generate(dag)
        content = output.files[0].content

        # Only False branch: normal filter (no fan-out)
        assert "step_2_filter_true" not in content
        assert "step_2_filter_false" not in content
        assert "WHERE" in content


class TestLakeflowStatsKeys:
    def test_stats_dict_has_all_required_keys(self, generator: LakeflowGenerator):
        """Stats dict should contain all keys needed by confidence scorer and reports."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        dag = WorkflowDAG()
        dag.add_node(read)

        output = generator.generate(dag)
        required_keys = {"total_nodes", "supported_nodes", "unsupported_nodes", "total_views", "warnings"}
        assert required_keys.issubset(output.stats.keys()), f"Missing stats keys: {required_keys - output.stats.keys()}"

    def test_empty_dag_stats(self, generator: LakeflowGenerator):
        """Empty DAG should produce zeroed stats."""
        dag = WorkflowDAG()
        output = generator.generate(dag, "empty")

        assert output.stats["total_nodes"] == 0
        assert output.stats["supported_nodes"] == 0
        assert output.stats["unsupported_nodes"] == 0
        assert output.stats["total_views"] == 0
        assert output.stats["warnings"] == 0
        assert output.files[0].filename == "empty_lakeflow.sql"
        assert len(output.files) == 2  # SQL + pipeline JSON
