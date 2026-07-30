"""Tests for the Designer notebook structural validator."""

from __future__ import annotations

import json

import pytest

from a2d.config import ConversionConfig, OutputFormat
from a2d.generators.designer import DesignerGenerator
from a2d.generators.designer_validation import validate_designer_notebook
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    AggAction,
    AggregationField,
    FilterNode,
    JoinKey,
    JoinNode,
    ReadNode,
    SummarizeNode,
    WriteNode,
)

yaml = pytest.importorskip("yaml")


@pytest.fixture
def generator() -> DesignerGenerator:
    return DesignerGenerator(ConversionConfig(output_format=OutputFormat.DESIGNER))


def _designer_ipynb(generator: DesignerGenerator, dag: WorkflowDAG) -> str:
    out = generator.generate(dag, "wf")
    return next(f.content for f in out.files if f.filename.endswith(".designer.ipynb"))


class TestValidGeneratedFiles:
    def test_simple_pipeline_is_valid(self, generator: DesignerGenerator):
        r1 = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/d/x.csv", file_format="csv")
        flt = FilterNode(node_id=2, expression="[amount] > 100")
        w = WriteNode(node_id=3, table_name="main.default.out")
        dag = WorkflowDAG()
        for n in (r1, flt, w):
            dag.add_node(n)
        dag.add_edge(1, 2)
        dag.add_edge(2, 3, origin_anchor="True")
        result = validate_designer_notebook(_designer_ipynb(generator, dag))
        assert result.is_valid, result.errors
        assert result.cell_count == 3

    def test_join_summarize_is_valid(self, generator: DesignerGenerator):
        left = ReadNode(node_id=1, source_type="database", table_name="l")
        right = ReadNode(node_id=2, source_type="database", table_name="r")
        jn = JoinNode(node_id=3, join_type="inner", join_keys=[JoinKey("id", "id")])
        summ = SummarizeNode(
            node_id=4,
            aggregations=[
                AggregationField("region", AggAction.GROUP_BY),
                AggregationField("amt", AggAction.SUM, "total"),
            ],
        )
        dag = WorkflowDAG()
        for n in (left, right, jn, summ):
            dag.add_node(n)
        dag.add_edge(1, 3, destination_anchor="Left")
        dag.add_edge(2, 3, destination_anchor="Right")
        dag.add_edge(3, 4, origin_anchor="Join")
        result = validate_designer_notebook(_designer_ipynb(generator, dag))
        assert result.is_valid, result.errors

    def test_result_is_truthy(self, generator: DesignerGenerator):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, table_name="t", source_type="database"))
        assert bool(validate_designer_notebook(_designer_ipynb(generator, dag)))


class TestDetectsCorruption:
    def _base(self, generator: DesignerGenerator) -> dict:
        dag = WorkflowDAG()
        r = ReadNode(node_id=1, table_name="t", source_type="database")
        w = WriteNode(node_id=2, table_name="out")
        dag.add_node(r)
        dag.add_node(w)
        dag.add_edge(1, 2)
        return json.loads(_designer_ipynb(generator, dag))

    def test_invalid_json(self):
        r = validate_designer_notebook("{ not json")
        assert not r.is_valid
        assert any("JSON" in e for e in r.errors)

    def test_wrong_nbformat(self, generator: DesignerGenerator):
        nb = self._base(generator)
        nb["nbformat"] = 3
        r = validate_designer_notebook(json.dumps(nb))
        assert not r.is_valid
        assert any("nbformat" in e for e in r.errors)

    def test_missing_notebook_metadata(self, generator: DesignerGenerator):
        nb = self._base(generator)
        nb["metadata"].pop("application/vnd.databricks.v1+notebook", None)
        r = validate_designer_notebook(json.dumps(nb))
        assert not r.is_valid

    def test_duplicate_nuid(self, generator: DesignerGenerator):
        nb = self._base(generator)
        key = "application/vnd.databricks.v1+cell"
        nb["cells"][1]["metadata"][key]["nuid"] = nb["cells"][0]["metadata"][key]["nuid"]
        r = validate_designer_notebook(json.dumps(nb))
        assert not r.is_valid
        assert any("duplicate nuid" in e for e in r.errors)

    def test_missing_nuid(self, generator: DesignerGenerator):
        nb = self._base(generator)
        key = "application/vnd.databricks.v1+cell"
        nb["cells"][0]["metadata"][key]["nuid"] = ""
        r = validate_designer_notebook(json.dumps(nb))
        assert not r.is_valid

    def test_corrupt_annotation_yaml(self, generator: DesignerGenerator):
        nb = self._base(generator)
        # Replace a cell's source with a broken YAML annotation.
        nb["cells"][0]["source"] = ['"""\n', "id: x\n", "  bad: : indent\n", '"""\n', "result = None\n"]
        r = validate_designer_notebook(json.dumps(nb))
        assert not r.is_valid

    def test_body_not_valid_python(self, generator: DesignerGenerator):
        nb = self._base(generator)
        nb["cells"][0]["source"] = [
            '"""\n', "id: x\n", "template: sql\n", "input: []\n", '"""\n',
            "result = (unclosed\n",
        ]
        r = validate_designer_notebook(json.dumps(nb))
        assert not r.is_valid
        assert any("not valid Python" in e for e in r.errors)

    def test_dangling_input_reference(self, generator: DesignerGenerator):
        nb = self._base(generator)
        # Point the second cell's input at a node id that isn't defined.
        src = "".join(nb["cells"][1]["source"])
        src = src.replace("node: step_1_", "node: step_999_")
        nb["cells"][1]["source"] = [line + "\n" for line in src.split("\n") if line]
        r = validate_designer_notebook(json.dumps(nb))
        assert not r.is_valid
        assert any("undefined node id" in e for e in r.errors)
