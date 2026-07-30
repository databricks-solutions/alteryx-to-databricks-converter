"""Tests for the Lakeflow Designer (.designer.ipynb) generator."""

from __future__ import annotations

import json

import pytest

from a2d.config import ConversionConfig, OutputFormat
from a2d.generators.designer import OPERATOR_VERSIONS, DesignerGenerator
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    AggAction,
    AggregationField,
    AutoFieldNode,
    CommentNode,
    CountRecordsNode,
    CrossTabNode,
    DataCleansingNode,
    FieldAction,
    FieldOperation,
    FilterNode,
    FormulaField,
    FormulaNode,
    JoinKey,
    JoinNode,
    PythonToolNode,
    ReadNode,
    RecordIDNode,
    SampleNode,
    SelectNode,
    SortField,
    SortNode,
    SummarizeNode,
    TileNode,
    UnionNode,
    UnsupportedNode,
    WriteNode,
)


@pytest.fixture
def config() -> ConversionConfig:
    return ConversionConfig(output_format=OutputFormat.DESIGNER)


@pytest.fixture
def generator(config: ConversionConfig) -> DesignerGenerator:
    return DesignerGenerator(config)


def _notebook(output) -> dict:
    """Parse the single generated .designer.ipynb into a dict (asserts valid JSON)."""
    assert len(output.files) == 1
    f = output.files[0]
    assert f.filename.endswith(".designer.ipynb")
    assert f.file_type == "ipynb"
    return json.loads(f.content)


def _cell_by_template(nb: dict, template: str) -> dict:
    for c in nb["cells"]:
        src = "".join(c["source"])
        if f"template: {template}\n" in src:
            return c
    raise AssertionError(f"no cell with template {template!r}")


def _annotation(cell: dict) -> str:
    """Return the YAML docstring block of a cell."""
    src = "".join(cell["source"])
    return src.split('"""')[1]


class TestNotebookStructure:
    def test_emits_valid_ipynb(self, generator: DesignerGenerator):
        node = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/d/x.csv", file_format="csv")
        dag = WorkflowDAG()
        dag.add_node(node)

        out = generator.generate(dag, "wf")
        nb = _notebook(out)

        assert nb["nbformat"] == 4
        assert nb["nbformat_minor"] == 0
        assert "application/vnd.databricks.v1+notebook" in nb["metadata"]
        assert nb["metadata"]["application/vnd.databricks.v1+notebook"]["notebookName"] == "wf"
        assert nb["metadata"]["application/vnd.databricks.v1+notebook"]["language"] == "python"

    def test_filename_uses_designer_extension(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv"))
        out = generator.generate(dag, "my_flow")
        assert out.files[0].filename == "my_flow.designer.ipynb"

    def test_each_cell_has_unique_nuid(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        r = ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv")
        flt = FilterNode(node_id=2, expression="[a] > 1")
        w = WriteNode(node_id=3, table_name="main.default.out")
        for n in (r, flt, w):
            dag.add_node(n)
        dag.add_edge(1, 2)
        dag.add_edge(2, 3, origin_anchor="True")

        nb = _notebook(generator.generate(dag, "wf"))
        nuids = [c["metadata"]["application/vnd.databricks.v1+cell"]["nuid"] for c in nb["cells"]]
        assert len(nuids) == len(set(nuids))
        assert all(nuids)  # none empty

    def test_cell_metadata_required_keys(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv"))
        nb = _notebook(generator.generate(dag, "wf"))
        meta = nb["cells"][0]["metadata"]["application/vnd.databricks.v1+cell"]
        for key in ("cellMetadata", "inputWidgets", "nuid", "showTitle", "tableResultSettingsMap", "title"):
            assert key in meta


class TestAnnotationContract:
    def test_annotation_has_required_fields(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv"))
        nb = _notebook(generator.generate(dag, "wf"))
        ann = _annotation(nb["cells"][0])
        for field in ("id:", "template:", "templateVersion:", "name:", "position:", "description:", "input:"):
            assert field in ann
        assert 'previewCodeHash: ""' in ann  # emitted empty (Designer recomputes)
        assert 'hash: ""' in ann
        assert 'previewMode: "1000"' in ann

    def test_template_versions_are_pinned(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv"))
        nb = _notebook(generator.generate(dag, "wf"))
        ann = _annotation(nb["cells"][0])
        assert f"templateVersion: {OPERATOR_VERSIONS['source']}" in ann


class TestNativeOperators:
    def test_file_read_becomes_source(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv"))
        nb = _notebook(generator.generate(dag, "wf"))
        src = "".join(_cell_by_template(nb, "source")["source"])
        assert "spark.read.format(\"csv\")" in src
        assert "path: /d/x.csv" in src

    def test_db_read_becomes_source_table(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, source_type="database", table_name="main.default.customers"))
        nb = _notebook(generator.generate(dag, "wf"))
        src = "".join(_cell_by_template(nb, "source")["source"])
        assert 'spark.read.table("main.default.customers")' in src

    def test_write_becomes_output(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        r = ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv")
        w = WriteNode(node_id=2, table_name="main.default.out", write_mode="overwrite")
        dag.add_node(r)
        dag.add_node(w)
        dag.add_edge(1, 2)
        nb = _notebook(generator.generate(dag, "wf"))
        assert _cell_by_template(nb, "output")

    def test_sort_becomes_sort(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        r = ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv")
        s = SortNode(node_id=2, sort_fields=[SortField("amount", ascending=False)])
        dag.add_node(r)
        dag.add_node(s)
        dag.add_edge(1, 2)
        nb = _notebook(generator.generate(dag, "wf"))
        src = "".join(_cell_by_template(nb, "sort")["source"])
        assert 'F.col("amount").desc()' in src

    def test_sample_first_n_becomes_limit(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        r = ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv")
        s = SampleNode(node_id=2, sample_method="first", n_records=50)
        dag.add_node(r)
        dag.add_node(s)
        dag.add_edge(1, 2)
        nb = _notebook(generator.generate(dag, "wf"))
        src = "".join(_cell_by_template(nb, "limit")["source"])
        assert "limit(50)" in src

    def test_union_becomes_combine(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        r1 = ReadNode(node_id=1, file_path="/d/a.csv", file_format="csv")
        r2 = ReadNode(node_id=2, file_path="/d/b.csv", file_format="csv")
        u = UnionNode(node_id=3)
        for n in (r1, r2, u):
            dag.add_node(n)
        dag.add_edge(1, 3)
        dag.add_edge(2, 3)
        nb = _notebook(generator.generate(dag, "wf"))
        combine = _cell_by_template(nb, "combine")
        ann = _annotation(combine)
        # combine@2 variadic port: both inputs wire to "data"
        assert ann.count("input_port: data") == 2

    def test_summarize_becomes_aggregate(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        r = ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv")
        summ = SummarizeNode(
            node_id=2,
            aggregations=[
                AggregationField("region", AggAction.GROUP_BY),
                AggregationField("amount", AggAction.SUM, "total"),
            ],
        )
        dag.add_node(r)
        dag.add_node(summ)
        dag.add_edge(1, 2)
        nb = _notebook(generator.generate(dag, "wf"))
        src = "".join(_cell_by_template(nb, "aggregate")["source"])
        assert 'groupBy("region")' in src
        assert 'F.sum("amount").alias("total")' in src

    def test_count_records_becomes_aggregate(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        r = ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv")
        c = CountRecordsNode(node_id=2, output_field="Count")
        dag.add_node(r)
        dag.add_node(c)
        dag.add_edge(1, 2)
        nb = _notebook(generator.generate(dag, "wf"))
        src = "".join(_cell_by_template(nb, "aggregate")["source"])
        assert "Count" in src

    def test_crosstab_becomes_pivot(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        r = ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv")
        ct = CrossTabNode(node_id=2, group_fields=["region"], header_field="month", value_field="sales", aggregation="Sum")
        dag.add_node(r)
        dag.add_node(ct)
        dag.add_edge(1, 2)
        out = generator.generate(dag, "wf")
        nb = _notebook(out)
        src = "".join(_cell_by_template(nb, "pivot")["source"])
        assert '.pivot("month")' in src
        assert any("CrossTab" in w for w in out.warnings)

    def test_select_becomes_transform(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        r = ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv")
        sel = SelectNode(
            node_id=2,
            field_operations=[
                FieldOperation("drop_me", action=FieldAction.DESELECT, selected=False),
                FieldOperation("old", action=FieldAction.RENAME, rename_to="new"),
            ],
        )
        dag.add_node(r)
        dag.add_node(sel)
        dag.add_edge(1, 2)
        nb = _notebook(generator.generate(dag, "wf"))
        src = "".join(_cell_by_template(nb, "transform")["source"])
        assert 'drop("drop_me")' in src
        assert 'withColumnRenamed("old", "new")' in src

    def test_formula_becomes_transform(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        r = ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv")
        fm = FormulaNode(node_id=2, formulas=[FormulaField("total", "[a] + [b]")])
        dag.add_node(r)
        dag.add_node(fm)
        dag.add_edge(1, 2)
        nb = _notebook(generator.generate(dag, "wf"))
        src = "".join(_cell_by_template(nb, "transform")["source"])
        assert 'withColumn("total"' in src

    def test_data_cleansing_becomes_transform(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        r = ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv")
        dc = DataCleansingNode(node_id=2, fields=["name"], trim_whitespace=True, modify_case="upper")
        dag.add_node(r)
        dag.add_node(dc)
        dag.add_edge(1, 2)
        nb = _notebook(generator.generate(dag, "wf"))
        src = "".join(_cell_by_template(nb, "transform")["source"])
        assert "upper(trim(`name`))" in src

    def test_python_tool_becomes_python(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        r = ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv")
        py = PythonToolNode(node_id=2, code="result = inputs['data']")
        dag.add_node(r)
        dag.add_node(py)
        dag.add_edge(1, 2)
        nb = _notebook(generator.generate(dag, "wf"))
        assert _cell_by_template(nb, "python")


class TestFilter:
    def test_filter_emits_both_ports(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        r = ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv")
        flt = FilterNode(node_id=2, expression="[amount] > 100")
        dag.add_node(r)
        dag.add_node(flt)
        dag.add_edge(1, 2)
        nb = _notebook(generator.generate(dag, "wf"))
        src = "".join(_cell_by_template(nb, "filter")["source"])
        assert "filtered_data" in src
        assert "excluded_data" in src

    def test_filter_true_branch_wires_filtered_data(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        r = ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv")
        flt = FilterNode(node_id=2, expression="[amount] > 100")
        w = WriteNode(node_id=3, table_name="main.default.kept")
        for n in (r, flt, w):
            dag.add_node(n)
        dag.add_edge(1, 2)
        dag.add_edge(2, 3, origin_anchor="True")
        nb = _notebook(generator.generate(dag, "wf"))
        out_cell = _cell_by_template(nb, "output")
        assert "output_port: filtered_data" in _annotation(out_cell)

    def test_filter_false_branch_wires_excluded_data(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        r = ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv")
        flt = FilterNode(node_id=2, expression="[amount] > 100")
        w = WriteNode(node_id=3, table_name="main.default.rejected")
        for n in (r, flt, w):
            dag.add_node(n)
        dag.add_edge(1, 2)
        dag.add_edge(2, 3, origin_anchor="False")
        nb = _notebook(generator.generate(dag, "wf"))
        out_cell = _cell_by_template(nb, "output")
        assert "output_port: excluded_data" in _annotation(out_cell)

    def test_empty_filter_expression_warns(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        r = ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv")
        flt = FilterNode(node_id=2, expression="")
        dag.add_node(r)
        dag.add_node(flt)
        dag.add_edge(1, 2)
        out = generator.generate(dag, "wf")
        assert any("no expression" in w for w in out.warnings)


class TestJoin:
    def test_join_wires_left_and_right_ports(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        left = ReadNode(node_id=1, file_path="/d/l.csv", file_format="csv")
        right = ReadNode(node_id=2, file_path="/d/r.csv", file_format="csv")
        jn = JoinNode(node_id=3, join_type="inner", join_keys=[JoinKey("id", "id")])
        for n in (left, right, jn):
            dag.add_node(n)
        dag.add_edge(1, 3, destination_anchor="Left")
        dag.add_edge(2, 3, destination_anchor="Right")
        nb = _notebook(generator.generate(dag, "wf"))
        ann = _annotation(_cell_by_template(nb, "join"))
        assert "input_port: left" in ann
        assert "input_port: right" in ann

    def test_join_output_port_is_joined_data(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        left = ReadNode(node_id=1, file_path="/d/l.csv", file_format="csv")
        right = ReadNode(node_id=2, file_path="/d/r.csv", file_format="csv")
        jn = JoinNode(node_id=3, join_type="inner", join_keys=[JoinKey("id", "id")])
        w = WriteNode(node_id=4, table_name="main.default.joined")
        for n in (left, right, jn, w):
            dag.add_node(n)
        dag.add_edge(1, 3, destination_anchor="Left")
        dag.add_edge(2, 3, destination_anchor="Right")
        dag.add_edge(3, 4, origin_anchor="Join")
        nb = _notebook(generator.generate(dag, "wf"))
        assert "output_port: joined_data" in _annotation(_cell_by_template(nb, "output"))

    def test_join_without_keys_warns(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        left = ReadNode(node_id=1, file_path="/d/l.csv", file_format="csv")
        right = ReadNode(node_id=2, file_path="/d/r.csv", file_format="csv")
        jn = JoinNode(node_id=3, join_type="inner", join_keys=[])
        for n in (left, right, jn):
            dag.add_node(n)
        dag.add_edge(1, 3, destination_anchor="Left")
        dag.add_edge(2, 3, destination_anchor="Right")
        out = generator.generate(dag, "wf")
        assert any("no keys" in w for w in out.warnings)


class TestFallback:
    def test_unmapped_tool_becomes_sql_cell(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        r = ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv")
        tile = TileNode(node_id=2, tile_count=4, tile_field="score", output_field="Tile")
        dag.add_node(r)
        dag.add_node(tile)
        dag.add_edge(1, 2)
        nb = _notebook(generator.generate(dag, "wf"))
        sql_cell = _cell_by_template(nb, "sql")
        assert "NTILE(4)" in "".join(sql_cell["source"])

    def test_fallback_references_upstream_cell_id(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        r = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/d/x.csv", file_format="csv")
        rid = RecordIDNode(node_id=2, output_field="RecordID")
        dag.add_node(r)
        dag.add_node(rid)
        dag.add_edge(1, 2)
        nb = _notebook(generator.generate(dag, "wf"))
        sql_cell = _cell_by_template(nb, "sql")
        # SQL body must reference the upstream source cell id, not a raw step name.
        assert "step_1_input_data" in "".join(sql_cell["source"])

    def test_native_vs_fallback_counts(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        r = ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv")
        flt = FilterNode(node_id=2, expression="[a] > 1")
        tile = TileNode(node_id=3, tile_count=4, tile_field="a", output_field="T")
        for n in (r, flt, tile):
            dag.add_node(n)
        dag.add_edge(1, 2)
        dag.add_edge(2, 3, origin_anchor="True")
        out = generator.generate(dag, "wf")
        assert out.stats["native_operators"] == 2  # source + filter
        assert out.stats["total_cells"] == 3


class TestSpecialNodes:
    def test_comment_becomes_markdown(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        dag.add_node(CommentNode(node_id=1, comment_text="Pipeline notes"))
        nb = _notebook(generator.generate(dag, "wf"))
        assert _cell_by_template(nb, "markdown")

    def test_unsupported_node_counted(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        r = ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv")
        un = UnsupportedNode(node_id=2, original_tool_type="Weird", unsupported_reason="no converter")
        dag.add_node(r)
        dag.add_node(un)
        dag.add_edge(1, 2)
        out = generator.generate(dag, "wf")
        assert out.stats["unsupported_nodes"] == 1

    def test_passthrough_autofield_forwards_id(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        r = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/d/x.csv", file_format="csv")
        af = AutoFieldNode(node_id=2)
        w = WriteNode(node_id=3, table_name="main.default.out")
        for n in (r, af, w):
            dag.add_node(n)
        dag.add_edge(1, 2)
        dag.add_edge(2, 3)
        nb = _notebook(generator.generate(dag, "wf"))
        # AutoField produces no cell; output wires straight to the source cell id.
        assert "output_port" in _annotation(_cell_by_template(nb, "output"))
        assert "step_1_input_data" in _annotation(_cell_by_template(nb, "output"))
        # only source + output cells (no autofield cell)
        assert len(nb["cells"]) == 2


class TestYamlQuoting:
    def test_special_chars_are_quoted(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        dag.add_node(CommentNode(node_id=1, comment_text="Hello: world, [test] {x}"))
        nb = _notebook(generator.generate(dag, "wf"))
        ann = _annotation(nb["cells"][0])
        assert 'md: "Hello: world, [test] {x}"' in ann

    def test_multiline_config_uses_block_literal(self, generator: DesignerGenerator):
        # Multi-line config values (e.g. a Note body) must use a YAML block
        # literal (|), never a double-quoted scalar (which folds newlines).
        dag = WorkflowDAG()
        dag.add_node(CommentNode(node_id=1, comment_text="line1\nline2"))
        nb = _notebook(generator.generate(dag, "wf"))
        ann = _annotation(nb["cells"][0])
        assert "md: |" in ann
        assert "    line1" in ann
        assert "    line2" in ann

    def test_inline_newline_escaped_in_scalar(self, generator: DesignerGenerator):
        # A short (inline) scalar with a newline is escaped, not emitted raw.
        node = ReadNode(node_id=1, source_type="database", table_name="a\nb")
        dag = WorkflowDAG()
        dag.add_node(node)
        nb = _notebook(generator.generate(dag, "wf"))
        ann = _annotation(nb["cells"][0])
        assert "\\n" in ann

    def test_plain_scalar_unquoted(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, source_type="database", table_name="plaintable"))
        nb = _notebook(generator.generate(dag, "wf"))
        ann = _annotation(nb["cells"][0])
        assert "table: plaintable" in ann  # no quotes needed


class TestCoverageStats:
    def test_stats_shape(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv"))
        out = generator.generate(dag, "wf")
        for key in ("total_nodes", "supported_nodes", "unsupported_nodes", "native_operators", "total_cells", "warnings"):
            assert key in out.stats

    def test_empty_dag(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        out = generator.generate(dag, "wf")
        nb = _notebook(out)
        assert nb["cells"] == []
        assert out.stats["total_nodes"] == 0
