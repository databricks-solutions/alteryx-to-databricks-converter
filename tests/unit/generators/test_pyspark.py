"""Tests for the PySpark notebook code generator."""

from __future__ import annotations

import pytest

from a2d.config import ConversionConfig
from a2d.generators.pyspark import PySparkGenerator
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    AggAction,
    AggregationField,
    FieldAction,
    FieldOperation,
    FilterNode,
    FormulaField,
    FormulaNode,
    JoinKey,
    JoinNode,
    LiteralDataNode,
    ReadNode,
    RecordIDNode,
    SelectNode,
    SortField,
    SortNode,
    SummarizeNode,
    UnionNode,
    UniqueNode,
    UnsupportedNode,
    WriteNode,
)


@pytest.fixture
def config() -> ConversionConfig:
    return ConversionConfig()


@pytest.fixture
def generator(config: ConversionConfig) -> PySparkGenerator:
    return PySparkGenerator(config)


def _make_dag_with_node(node, predecessors=None):
    """Helper to build a simple DAG with one node, optionally connected to predecessors."""
    dag = WorkflowDAG()
    if predecessors:
        for pred in predecessors:
            dag.add_node(pred)
    dag.add_node(node)
    if predecessors:
        for pred in predecessors:
            dag.add_edge(pred.node_id, node.node_id)
    return dag


class TestReadNode:
    def test_simple_read_node(self, generator: PySparkGenerator):
        """Generate code for a ReadNode producing a spark.read call."""
        node = ReadNode(
            node_id=1,
            original_tool_type="Input Data",
            file_path="/data/input.csv",
            file_format="csv",
            has_header=True,
        )
        dag = _make_dag_with_node(node)
        output = generator.generate(dag, "test_workflow")

        assert len(output.files) == 1
        content = output.files[0].content
        assert 'spark.read.format("csv")' in content
        assert '"/data/input.csv"' in content
        assert "df_1" in content

    def test_read_node_database(self, generator: PySparkGenerator):
        """ReadNode with database source generates spark.table()."""
        node = ReadNode(
            node_id=1,
            original_tool_type="Input Data",
            source_type="database",
            table_name="catalog.schema.my_table",
        )
        dag = _make_dag_with_node(node)
        output = generator.generate(dag)
        content = output.files[0].content
        assert 'spark.table("catalog.schema.my_table")' in content


class TestFilterNode:
    def test_filter_node_generates_only_used_branches(self, generator: PySparkGenerator):
        """Filter should only emit branches that are connected downstream."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        filt = FilterNode(
            node_id=2,
            original_tool_type="Filter",
            expression="[Age] > 25",
        )
        # Downstream node wired to False output only
        from a2d.ir.nodes import BrowseNode

        browse = BrowseNode(node_id=3, original_tool_type="Browse")
        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(filt)
        dag.add_node(browse)
        dag.add_edge(1, 2)
        dag.add_edge(2, 3, origin_anchor="False", destination_anchor="Input")

        output = generator.generate(dag)
        content = output.files[0].content

        # Only the false branch should be emitted
        assert "df_2_false" in content
        assert "df_2_true" not in content
        assert ".filter(" in content

    def test_filter_node_both_branches(self, generator: PySparkGenerator):
        """Filter with both branches wired should emit both."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        filt = FilterNode(
            node_id=2,
            original_tool_type="Filter",
            expression="[Age] > 25",
        )
        from a2d.ir.nodes import BrowseNode

        browse_true = BrowseNode(node_id=3, original_tool_type="Browse")
        browse_false = BrowseNode(node_id=4, original_tool_type="Browse")
        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(filt)
        dag.add_node(browse_true)
        dag.add_node(browse_false)
        dag.add_edge(1, 2)
        dag.add_edge(2, 3, origin_anchor="True", destination_anchor="Input")
        dag.add_edge(2, 4, origin_anchor="False", destination_anchor="Input")

        output = generator.generate(dag)
        content = output.files[0].content

        assert "df_2_true" in content
        assert "df_2_false" in content
        assert ".filter(" in content

    def test_filter_node_empty_expression_does_not_crash(self, generator: PySparkGenerator):
        """A FilterNode with an empty expression should generate a passthrough, not crash."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        filt = FilterNode(
            node_id=2,
            original_tool_type="Filter",
            expression="",
        )
        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(filt)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content

        # Should produce a passthrough with a TODO comment
        assert "df_2_true" in content
        assert "TODO" in content
        # Should NOT crash or contain .filter() call
        assert ".filter(_filter_cond" not in content
        # Should produce a warning
        assert any("no expression" in w for w in output.warnings)

    def test_filter_node_whitespace_expression_does_not_crash(self, generator: PySparkGenerator):
        """A FilterNode with a whitespace-only expression should be treated as empty."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        filt = FilterNode(
            node_id=2,
            original_tool_type="Filter",
            expression="   ",
        )
        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(filt)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content
        assert "TODO" in content
        assert any("no expression" in w for w in output.warnings)


class TestFormulaNode:
    def test_formula_node_single_field_uses_withcolumns(self, generator: PySparkGenerator):
        """A single-field formula produces a withColumns({...}) call."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        formula = FormulaNode(
            node_id=2,
            original_tool_type="Formula",
            formulas=[
                FormulaField(
                    output_field="FullName",
                    expression='[FirstName] + " " + [LastName]',
                )
            ],
        )
        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(formula)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content

        assert 'withColumns({"FullName"' in content or 'withColumns({\n    "FullName"' in content
        assert "df_2" in content

    def test_formula_node_multiple_independent_fields_uses_withcolumns(self, generator: PySparkGenerator):
        """Multiple independent formulas are merged into a single withColumns call."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        formula = FormulaNode(
            node_id=2,
            original_tool_type="Formula",
            formulas=[
                FormulaField(output_field="A", expression="1"),
                FormulaField(output_field="B", expression="2"),
            ],
        )
        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(formula)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content

        # Should be exactly one withColumns call, not two separate withColumn calls
        assert content.count(".withColumns(") == 1
        assert '"A"' in content
        assert '"B"' in content

    def test_formula_node_dependent_fields_uses_sequential_withcolumn(self, generator: PySparkGenerator):
        """Formulas where B references A's output field fall back to sequential withColumn calls."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        formula = FormulaNode(
            node_id=2,
            original_tool_type="Formula",
            formulas=[
                FormulaField(output_field="A", expression="[X] + 1"),
                FormulaField(output_field="B", expression="[A] * 2"),  # B depends on A
            ],
        )
        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(formula)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content

        # Sequential: two separate withColumn calls
        assert content.count('.withColumn("A"') == 1
        assert content.count('.withColumn("B"') == 1


class TestJoinNode:
    def test_join_node_with_keys(self, generator: PySparkGenerator):
        """Join two inputs produces .join() with key condition."""
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

        assert "df_3_join" in content
        assert ".join(" in content
        assert '"id"' in content
        assert '"inner"' in content


class TestSummarizeNode:
    def test_summarize_node(self, generator: PySparkGenerator):
        """Summarize produces groupBy + agg."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        summ = SummarizeNode(
            node_id=2,
            original_tool_type="Summarize",
            aggregations=[
                AggregationField(field_name="Department", action=AggAction.GROUP_BY),
                AggregationField(
                    field_name="Salary",
                    action=AggAction.SUM,
                    output_field_name="TotalSalary",
                ),
                AggregationField(
                    field_name="EmployeeID",
                    action=AggAction.COUNT,
                    output_field_name="HeadCount",
                ),
            ],
        )

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(summ)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content

        assert "groupBy(" in content
        assert '"Department"' in content
        assert "F.sum" in content
        assert '"TotalSalary"' in content
        assert "F.count" in content
        assert '"HeadCount"' in content


class TestSelectNode:
    def test_select_node_renames(self, generator: PySparkGenerator):
        """SelectNode with renames generates .withColumnsRenamed()."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        sel = SelectNode(
            node_id=2,
            original_tool_type="Select",
            field_operations=[
                FieldOperation(
                    field_name="OldName",
                    action=FieldAction.RENAME,
                    rename_to="NewName",
                    selected=True,
                ),
                FieldOperation(
                    field_name="DropMe",
                    action=FieldAction.DESELECT,
                    selected=False,
                ),
            ],
        )

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(sel)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content

        assert 'withColumnsRenamed({"OldName": "NewName"})' in content
        assert 'drop("DropMe")' in content


class TestSortNode:
    def test_sort_node(self, generator: PySparkGenerator):
        """SortNode generates .orderBy() with asc/desc."""
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

        assert ".orderBy(" in content
        assert '"Name"' in content
        assert ".asc()" in content
        assert '"Age"' in content
        assert ".desc()" in content


class TestUnsupportedNode:
    def test_unsupported_node_concise(self, generator: PySparkGenerator):
        """UnsupportedNode generates a concise comment by default."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        unsup = UnsupportedNode(
            node_id=2,
            original_tool_type="SpatialMatch",
            unsupported_reason="Geospatial tools are not supported",
        )

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(unsup)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content

        assert "SpatialMatch" in content
        assert "manual conversion required" in content
        assert len(output.warnings) >= 1

    def test_unsupported_node_verbose(self):
        """UnsupportedNode emits detailed stubs when verbose_unsupported=True."""
        from a2d.config import ConversionConfig

        verbose_gen = PySparkGenerator(ConversionConfig(verbose_unsupported=True))
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        unsup = UnsupportedNode(
            node_id=2,
            original_tool_type="SpatialMatch",
            unsupported_reason="Geospatial tools are not supported",
        )

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(unsup)
        dag.add_edge(1, 2)

        output = verbose_gen.generate(dag)
        content = output.files[0].content

        assert "UNSUPPORTED" in content
        assert "SpatialMatch" in content
        assert "Geospatial tools are not supported" in content
        assert "TODO: Manual conversion required." in content


class TestNotebookFormat:
    def test_notebook_format(self, generator: PySparkGenerator):
        """Verify Databricks notebook header and command separators."""
        node = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        dag = _make_dag_with_node(node)
        output = generator.generate(dag)
        content = output.files[0].content

        assert content.startswith("# Databricks notebook source")
        assert "# COMMAND ----------" in content
        assert "from pyspark.sql import functions as F" in content
        assert "from pyspark.sql import Window" in content


class TestFullPipeline:
    def test_full_pipeline(self, generator: PySparkGenerator):
        """Build a small DAG (read -> filter -> summarize -> write), generate notebook."""
        read = ReadNode(
            node_id=1,
            original_tool_type="Input Data",
            file_path="/data/employees.csv",
            file_format="csv",
            has_header=True,
        )
        filt = FilterNode(
            node_id=2,
            original_tool_type="Filter",
            expression="[Active] = 1",
        )
        summ = SummarizeNode(
            node_id=3,
            original_tool_type="Summarize",
            aggregations=[
                AggregationField(field_name="Department", action=AggAction.GROUP_BY),
                AggregationField(field_name="Salary", action=AggAction.AVG, output_field_name="AvgSalary"),
            ],
        )
        write = WriteNode(
            node_id=4,
            original_tool_type="Output Data",
            file_path="/output/summary.parquet",
            file_format="parquet",
            write_mode="overwrite",
        )

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(filt)
        dag.add_node(summ)
        dag.add_node(write)
        dag.add_edge(1, 2)
        dag.add_edge(2, 3, origin_anchor="True")
        dag.add_edge(3, 4)

        output = generator.generate(dag, "employees_pipeline")
        assert len(output.files) == 1

        content = output.files[0].content
        assert output.files[0].filename == "employees_pipeline.py"

        # Verify pipeline steps exist
        assert "spark.read" in content
        assert ".filter(" in content
        assert "groupBy(" in content
        assert ".write" in content

        # Verify topological flow (df_1 used by filter, filter result used by summarize)
        assert "df_1" in content
        assert "df_2_true" in content
        assert "df_3" in content

        # Verify notebook structure
        assert content.startswith("# Databricks notebook source")
        command_separators = content.count("# COMMAND ----------")
        assert command_separators >= 4  # imports + at least 4 node cells


class TestEdgeCases:
    def test_write_to_table(self, generator: PySparkGenerator):
        """WriteNode with database destination generates .saveAsTable()."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        write = WriteNode(
            node_id=2,
            original_tool_type="Output Data",
            destination_type="database",
            table_name="catalog.schema.output_table",
            write_mode="append",
        )

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(write)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content
        assert "saveAsTable" in content
        assert "catalog.schema.output_table" in content
        assert "append" in content

    def test_literal_data_node(self, generator: PySparkGenerator):
        """LiteralDataNode generates createDataFrame with rows and schema."""
        node = LiteralDataNode(
            node_id=1,
            original_tool_type="Text Input",
            field_names=["Name", "Age"],
            data_rows=[["Alice", "30"], ["Bob", "25"]],
        )
        dag = _make_dag_with_node(node)
        output = generator.generate(dag)
        content = output.files[0].content

        assert "createDataFrame" in content
        assert "Alice" in content
        assert "Name" in content

    def test_union_node(self, generator: PySparkGenerator):
        """UnionNode generates .unionByName()."""
        r1 = ReadNode(node_id=1, original_tool_type="Input", file_path="/a.csv", file_format="csv")
        r2 = ReadNode(node_id=2, original_tool_type="Input", file_path="/b.csv", file_format="csv")
        union = UnionNode(node_id=3, original_tool_type="Union", allow_missing=True)

        dag = WorkflowDAG()
        dag.add_node(r1)
        dag.add_node(r2)
        dag.add_node(union)
        dag.add_edge(1, 3, destination_anchor="Input1")
        dag.add_edge(2, 3, destination_anchor="Input2")

        output = generator.generate(dag)
        content = output.files[0].content
        assert "unionByName" in content
        assert "allowMissingColumns=True" in content

    def test_unique_node(self, generator: PySparkGenerator):
        """UniqueNode generates dropDuplicates and subtract."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        unique = UniqueNode(
            node_id=2,
            original_tool_type="Unique",
            key_fields=["CustomerID", "Email"],
        )

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(unique)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content
        assert "dropDuplicates" in content
        assert "CustomerID" in content
        assert "df_2_unique" in content
        assert "df_2_duplicate" in content

    def test_record_id_node(self, generator: PySparkGenerator):
        """RecordIDNode generates monotonically_increasing_id."""
        read = ReadNode(node_id=1, original_tool_type="Input", file_path="/data.csv", file_format="csv")
        rid = RecordIDNode(
            node_id=2,
            original_tool_type="RecordID",
            output_field="RowNum",
            starting_value=1,
        )

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(rid)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content
        assert "monotonically_increasing_id" in content
        assert "RowNum" in content

    def test_stats_tracking(self, generator: PySparkGenerator):
        """Verify stats include total_nodes and unsupported_nodes."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        unsup = UnsupportedNode(node_id=2, original_tool_type="Mystery", unsupported_reason="Unknown")

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(unsup)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        assert output.stats["total_nodes"] == 2
        assert output.stats["unsupported_nodes"] == 1


class TestReadNodeInlining:
    """Tests for single-use DB ReadNode inlining (Venkata feedback)."""

    def test_single_use_db_read_inlines_into_downstream(self, generator: PySparkGenerator):
        """A DB ReadNode with exactly 1 successor is inlined — no df_N variable emitted."""
        read = ReadNode(
            node_id=1,
            original_tool_type="Input Data",
            source_type="database",
            query="select * from my_table",
            connection_string="aka:MYCONN",
        )
        formula = FormulaNode(
            node_id=2,
            original_tool_type="Formula",
            formulas=[FormulaField(output_field="x", expression="[x] + 1")],
        )
        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(formula)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content

        # The intermediate df_1 variable should NOT appear as an assignment
        assert "df_1 = spark.sql" not in content
        # The SQL expression should be inlined into the downstream cell
        assert 'spark.sql("""select * from my_table""")' in content
        # The downstream step comment must carry the inline attribution
        assert "[input: Step 1 (Input)" in content
        assert "TODO: map to Unity Catalog" in content

    def test_fan_out_db_read_stays_named(self, generator: PySparkGenerator):
        """A DB ReadNode with 2+ successors keeps its named variable (inlining would run SQL twice)."""
        read = ReadNode(
            node_id=1,
            original_tool_type="Input Data",
            source_type="database",
            query="select * from my_table",
        )
        formula1 = FormulaNode(
            node_id=2,
            original_tool_type="Formula",
            formulas=[FormulaField(output_field="a", expression="1")],
        )
        formula2 = FormulaNode(
            node_id=3,
            original_tool_type="Formula",
            formulas=[FormulaField(output_field="b", expression="2")],
        )
        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(formula1)
        dag.add_node(formula2)
        dag.add_edge(1, 2)
        dag.add_edge(1, 3)

        output = generator.generate(dag)
        content = output.files[0].content

        # Named variable must be present
        assert "df_1 = spark.sql" in content
        # Fan-out comment must list the downstream steps
        assert "shared by Steps" in content

    def test_db_read_todo_includes_unity_catalog_sample(self, generator: PySparkGenerator):
        """DB ReadNode TODO comment includes concrete Unity Catalog syntax options."""
        read = ReadNode(
            node_id=1,
            original_tool_type="Input Data",
            source_type="database",
            query="select * from t",
            connection_string="aka:CONN",
        )
        # Give it 2 successors so it stays named (making it easier to inspect its own cell)
        f1 = FormulaNode(
            node_id=2, original_tool_type="Formula", formulas=[FormulaField(output_field="x", expression="1")]
        )
        f2 = FormulaNode(
            node_id=3, original_tool_type="Formula", formulas=[FormulaField(output_field="y", expression="2")]
        )
        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(f1)
        dag.add_node(f2)
        dag.add_edge(1, 2)
        dag.add_edge(1, 3)

        output = generator.generate(dag)
        content = output.files[0].content

        assert "spark.table(" in content
        assert "catalog.schema.table_name" in content
        assert "jdbc" in content.lower()


class TestStringEscaping:
    """Tests for _esc() applied to paths and field names (Venkata syntax error fix)."""

    def test_path_with_double_quote_does_not_produce_syntax_error(self, generator: PySparkGenerator):
        """A file path containing a double-quote must be escaped so generated code is valid Python."""
        import ast

        node = ReadNode(
            node_id=1,
            original_tool_type="Input Data",
            file_path='/data/folder"name"/file.csv',
            file_format="csv",
        )
        dag = _make_dag_with_node(node)
        output = generator.generate(dag)
        content = output.files[0].content
        # Must parse as valid Python
        ast.parse(content)
        # The escaped quote must appear in the path string
        assert '\\"' in content

    def test_write_path_with_double_quote_is_escaped(self, generator: PySparkGenerator):
        """WriteNode path containing a double-quote is safely escaped."""
        import ast

        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/in.csv", file_format="csv")
        write = WriteNode(
            node_id=2,
            original_tool_type="Output Data",
            file_path='/out/folder"name"/result.csv',
            file_format="csv",
        )
        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(write)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content
        ast.parse(content)

    def test_esc_helper_escapes_backslash_and_quote(self, generator: PySparkGenerator):
        """_esc() escapes both backslashes and double-quotes."""
        assert generator._esc("C:\\path") == "C:\\\\path"
        assert generator._esc('say "hi"') == 'say \\"hi\\"'
        assert generator._esc('C:\\"test"') == 'C:\\\\\\"test\\"'


class TestSQLNormalization:
    """Tests for normalize_sql_for_spark() and its application in generators."""

    def test_getdate_replaced_with_current_timestamp(self):
        from a2d.utils.types import normalize_sql_for_spark

        sql = "SELECT GETDATE() AS run_date FROM my_table"
        result, warns = normalize_sql_for_spark(sql)
        assert "CURRENT_TIMESTAMP()" in result
        assert "GETDATE" not in result
        assert warns == []

    def test_getdate_case_insensitive(self):
        from a2d.utils.types import normalize_sql_for_spark

        for variant in ["GETDATE()", "getdate()", "GetDate()", "GETDATE (  )"]:
            result, _ = normalize_sql_for_spark(f"SELECT {variant} FROM t")
            assert "CURRENT_TIMESTAMP()" in result

    def test_now_replaced_with_current_timestamp(self):
        from a2d.utils.types import normalize_sql_for_spark

        result, _ = normalize_sql_for_spark("SELECT NOW() AS ts FROM t")
        assert "CURRENT_TIMESTAMP()" in result
        assert "NOW()" not in result

    def test_sysdate_replaced_with_current_timestamp(self):
        from a2d.utils.types import normalize_sql_for_spark

        result, _ = normalize_sql_for_spark("SELECT SYSDATE AS ts FROM t")
        assert "CURRENT_TIMESTAMP()" in result
        assert "SYSDATE" not in result

    def test_double_quoted_alias_converted_to_backtick(self):
        from a2d.utils.types import normalize_sql_for_spark

        result, _ = normalize_sql_for_spark('SELECT col AS "account_number" FROM t')
        assert "`account_number`" in result
        assert '"account_number"' not in result

    def test_hyphen_in_alias_replaced_with_underscore(self):
        from a2d.utils.types import normalize_sql_for_spark

        result, _ = normalize_sql_for_spark('SELECT col AS "account-number" FROM t')
        assert "`account_number`" in result
        assert "account-number" not in result

    def test_combined_getdate_and_double_quote_alias(self):
        from a2d.utils.types import normalize_sql_for_spark

        sql = 'SELECT GETDATE() AS "run-date", acct AS "acct-num" FROM schema.table'
        result, _ = normalize_sql_for_spark(sql)
        assert "CURRENT_TIMESTAMP()" in result
        assert "`run_date`" in result
        assert "`acct_num`" in result
        assert "GETDATE" not in result

    def test_no_change_when_no_problematic_patterns(self):
        from a2d.utils.types import normalize_sql_for_spark

        sql = "SELECT a, b, c FROM my_table WHERE d = 1"
        result, warns = normalize_sql_for_spark(sql)
        assert result == sql
        assert warns == []

    def test_current_date_replaced_with_spark_function(self):
        from a2d.utils.types import normalize_sql_for_spark

        sql = "SELECT (Current Date) as RUN_DT FROM my_table"
        result, _ = normalize_sql_for_spark(sql)
        assert "CURRENT_DATE()" in result
        assert "Current Date" not in result

    def test_current_time_replaced_with_spark_function(self):
        from a2d.utils.types import normalize_sql_for_spark

        sql = "SELECT (Current Time) as RUN_TM FROM my_table"
        result, _ = normalize_sql_for_spark(sql)
        assert "CURRENT_TIME()" in result
        assert "Current Time" not in result

    def test_db_read_node_sql_is_normalized_in_output(self, generator: PySparkGenerator):
        """ReadNode with GETDATE() and double-quoted alias emits normalized SQL."""
        query = 'SELECT GETDATE() AS "run-date" FROM schema.table'
        node = ReadNode(
            node_id=1,
            original_tool_type="Input Data",
            source_type="database",
            query=query,
            connection_string="aka:test123",
        )
        dag = WorkflowDAG()
        dag.add_node(node)
        output = generator.generate(dag)
        content = output.files[0].content
        assert "CURRENT_TIMESTAMP()" in content
        assert "`run_date`" in content
        assert "GETDATE" not in content


class TestDateTimeNodeNowMode:
    """Tests for DateTimeNode 'now' conversion mode."""

    def test_now_mode_emits_current_timestamp(self, generator: PySparkGenerator):
        """DateTimeNode with conversion_mode='now' generates F.current_timestamp()."""
        from a2d.ir.nodes import DateTimeNode

        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/in.csv", file_format="csv")
        dt = DateTimeNode(
            node_id=2,
            original_tool_type="DateTime",
            input_field="some_field",
            output_field="run_timestamp",
            conversion_mode="now",
        )
        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(dt)
        dag.add_edge(1, 2)
        output = generator.generate(dag)
        content = output.files[0].content
        assert "F.current_timestamp()" in content
        assert "run_timestamp" in content
        # Should NOT be a passthrough
        assert 'F.col("some_field")' not in content


class TestWriteNodeOutputFixes:
    """Tests for Excel write and UNC path handling in WriteNode generation."""

    def test_write_xlsx_emits_todo_not_format_call(self, generator: PySparkGenerator):
        """Excel output should emit a TODO block, not a broken .write.format('xlsx') call."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/in.csv", file_format="csv")
        write = WriteNode(
            node_id=2,
            original_tool_type="Output Data",
            file_path=r"\\server\share\output.xlsx|||Sheet1",
            file_format="xlsx",
        )
        dag = _make_dag_with_node(write, predecessors=[read])
        dag.add_edge(1, 2)
        output = generator.generate(dag)
        content = output.files[0].content
        assert "# TODO: Excel write not supported natively in Databricks." in content
        assert '.write.format("xlsx")' not in content
        assert '.write.format("xlsx|||' not in content
        assert "Sheet1" in content  # sheet name preserved in comment

    def test_write_unc_path_uses_todo_placeholder(self, generator: PySparkGenerator):
        """UNC path output should have a TODO placeholder in .save(), not the original UNC path."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/in.csv", file_format="csv")
        write = WriteNode(
            node_id=2,
            original_tool_type="Output Data",
            file_path=r"\\nasserver\share\output.csv",
            file_format="csv",
        )
        dag = _make_dag_with_node(write, predecessors=[read])
        dag.add_edge(1, 2)
        output = generator.generate(dag)
        content = output.files[0].content
        assert "# WARNING: local/network path detected" in content
        assert "# Original path:" in content
        # The .save() call must NOT contain the raw UNC path
        assert '.save("\\\\nasserver' not in content
        assert '.save("# TODO:' in content


class TestDynamicInputDateWarning:
    """Tests for ISO date placeholder warning in DynamicInput ModifySQL generation."""

    def test_dynamic_input_iso_date_placeholder_emits_normalization_helper(self, generator: PySparkGenerator):
        """DynamicInput with ISO date placeholders should emit the _to_iso_date helper function."""
        from a2d.ir.nodes import DynamicInputNode

        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/in.csv", file_format="csv")
        dyn = DynamicInputNode(
            node_id=2,
            original_tool_type="DynamicInput",
            mode="ModifySQL",
            template_query="SELECT * FROM t WHERE dt = '2023-01-01'",
            template_connection="aka:some-connection",
            modifications=[{"field": "ReportDate", "replace_text": "2023-01-01"}],
        )
        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(dyn)
        dag.add_edge(1, 2)
        output = generator.generate(dag)
        content = output.files[0].content
        assert "def _to_iso_date_2" in content
        assert "strptime" in content
        assert '_to_iso_date_2(_row["ReportDate"])' in content

    def test_dynamic_input_non_date_placeholder_no_note(self, generator: PySparkGenerator):
        """DynamicInput with non-date placeholders should NOT emit the ISO date NOTE."""
        from a2d.ir.nodes import DynamicInputNode

        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/in.csv", file_format="csv")
        dyn = DynamicInputNode(
            node_id=2,
            original_tool_type="DynamicInput",
            mode="ModifySQL",
            template_query="SELECT * FROM t WHERE name = 'ACME'",
            template_connection="aka:some-connection",
            modifications=[{"field": "CompanyName", "replace_text": "ACME"}],
        )
        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(dyn)
        dag.add_edge(1, 2)
        output = generator.generate(dag)
        content = output.files[0].content
        assert "# NOTE: SQL expects ISO date format" not in content


class TestDynamicInputDateNormalization:
    """TDD: RED tests for date normalization helper and StructType fallback fixes."""

    def _make_dyn_iso(self, generator, modifications):
        from a2d.ir.nodes import DynamicInputNode

        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/in.csv", file_format="csv")
        dyn = DynamicInputNode(
            node_id=6,
            original_tool_type="DynamicInput",
            mode="ModifySQL",
            template_query="SELECT * FROM t WHERE dt1 = '2023-01-01' AND dt2 = '2023-01-02'",
            template_connection="aka:conn",
            modifications=modifications,
        )
        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(dyn)
        dag.add_edge(1, 6)
        return generator.generate(dag).files[0].content

    def test_r1_iso_placeholder_emits_normalization_helper(self, generator: PySparkGenerator):
        """R1 (RED): ISO date placeholder → helper function _to_iso_date_6 is defined."""
        content = self._make_dyn_iso(
            generator,
            [
                {"field": "ReportDate", "replace_text": "2023-01-01"},
            ],
        )
        assert "def _to_iso_date_6" in content
        assert "strptime" in content

    def test_r2_iso_placeholder_replace_uses_helper_not_raw_str(self, generator: PySparkGenerator):
        """R2 (RED): ISO date placeholder → .replace() uses helper, not raw str(_row[...])."""
        content = self._make_dyn_iso(
            generator,
            [
                {"field": "ReportDate", "replace_text": "2023-01-01"},
            ],
        )
        assert 'str(_row["ReportDate"])' not in content
        assert '_to_iso_date_6(_row["ReportDate"])' in content

    def test_r3_non_date_placeholder_uses_raw_str_no_helper(self, generator: PySparkGenerator):
        """R3 (RED): Non-date placeholder → raw str() is used, no helper emitted."""
        from a2d.ir.nodes import DynamicInputNode

        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/in.csv", file_format="csv")
        dyn = DynamicInputNode(
            node_id=6,
            original_tool_type="DynamicInput",
            mode="ModifySQL",
            template_query="SELECT * FROM t WHERE name = 'ACME'",
            template_connection="aka:conn",
            modifications=[{"field": "CompanyName", "replace_text": "ACME"}],
        )
        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(dyn)
        dag.add_edge(1, 6)
        content = generator.generate(dag).files[0].content
        assert 'str(_row["CompanyName"])' in content
        assert "def _to_iso_date_6" not in content

    def test_r4_empty_fallback_uses_struct_type_not_schema_none(self, generator: PySparkGenerator):
        """R4 (RED): Empty DataFrame fallback must use StructType([]), not schema=None."""
        content = self._make_dyn_iso(
            generator,
            [
                {"field": "ReportDate", "replace_text": "2023-01-01"},
            ],
        )
        assert "schema=None" not in content
        assert "StructType([])" in content
