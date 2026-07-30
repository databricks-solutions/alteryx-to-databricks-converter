"""Tests for the pandas reference executor."""

from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    AggAction,
    AggregationField,
    CountRecordsNode,
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
    SampleNode,
    SelectNode,
    SortField,
    SortNode,
    SummarizeNode,
    UnionNode,
    WriteNode,
)
from a2d.verification.reference import ReferenceExecutor


def _sink(res, node_id):
    return res.outputs[node_id]


class TestSources:
    def test_read_from_source_data(self):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, table_name="t"))
        res = ReferenceExecutor({"t": pd.DataFrame({"a": [1, 2]})}).execute(dag)
        assert _sink(res, 1)["a"].tolist() == [1, 2]

    def test_read_missing_source_is_skipped(self):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, table_name="t"))
        res = ReferenceExecutor({}).execute(dag)
        assert res.skipped and res.skipped[0][0] == 1
        assert not res.fully_supported

    def test_literal_data_uses_embedded_rows(self):
        dag = WorkflowDAG()
        dag.add_node(
            LiteralDataNode(node_id=1, field_names=["x", "y"], data_rows=[["1", "a"], ["2", "b"]])
        )
        res = ReferenceExecutor({}).execute(dag)
        out = _sink(res, 1)
        assert out["x"].tolist() == [1, 2]  # numeric coercion
        assert out["y"].tolist() == ["a", "b"]


class TestTransforms:
    def _read(self, data):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, table_name="t"))
        return dag, {"t": data}

    def test_filter(self):
        dag, src = self._read(pd.DataFrame({"v": [5, 15, 25]}))
        dag.add_node(FilterNode(node_id=2, expression="[v] > 10"))
        dag.add_edge(1, 2)
        res = ReferenceExecutor(src).execute(dag)
        assert _sink(res, 2)["v"].tolist() == [15, 25]

    def test_filter_false_branch(self):
        dag, src = self._read(pd.DataFrame({"v": [5, 15, 25]}))
        dag.add_node(FilterNode(node_id=2, expression="[v] > 10"))
        dag.add_node(WriteNode(node_id=3, table_name="kept"))
        dag.add_node(WriteNode(node_id=4, table_name="rej"))
        dag.add_edge(1, 2)
        dag.add_edge(2, 3, origin_anchor="True")
        dag.add_edge(2, 4, origin_anchor="False")
        res = ReferenceExecutor(src).execute(dag)
        assert _sink(res, 3)["v"].tolist() == [15, 25]
        assert _sink(res, 4)["v"].tolist() == [5]

    def test_formula(self):
        dag, src = self._read(pd.DataFrame({"a": [1, 2], "b": [10, 20]}))
        dag.add_node(FormulaNode(node_id=2, formulas=[FormulaField("c", "[a] + [b]")]))
        dag.add_edge(1, 2)
        res = ReferenceExecutor(src).execute(dag)
        assert _sink(res, 2)["c"].tolist() == [11, 22]

    def test_select_drop_and_rename(self):
        dag, src = self._read(pd.DataFrame({"keep": [1], "drop": [2], "old": [3]}))
        dag.add_node(
            SelectNode(
                node_id=2,
                field_operations=[
                    FieldOperation("drop", action=FieldAction.DESELECT, selected=False),
                    FieldOperation("old", action=FieldAction.RENAME, rename_to="new"),
                ],
            )
        )
        dag.add_edge(1, 2)
        out = _sink(ReferenceExecutor(src).execute(dag), 2)
        assert "drop" not in out.columns
        assert "new" in out.columns and "old" not in out.columns

    def test_sort(self):
        dag, src = self._read(pd.DataFrame({"v": [3, 1, 2]}))
        dag.add_node(SortNode(node_id=2, sort_fields=[SortField("v", ascending=True)]))
        dag.add_edge(1, 2)
        assert _sink(ReferenceExecutor(src).execute(dag), 2)["v"].tolist() == [1, 2, 3]

    def test_sample_first_n(self):
        dag, src = self._read(pd.DataFrame({"v": [1, 2, 3, 4, 5]}))
        dag.add_node(SampleNode(node_id=2, sample_method="first", n_records=2))
        dag.add_edge(1, 2)
        assert _sink(ReferenceExecutor(src).execute(dag), 2)["v"].tolist() == [1, 2]

    def test_record_id(self):
        dag, src = self._read(pd.DataFrame({"v": [9, 8, 7]}))
        dag.add_node(RecordIDNode(node_id=2, output_field="rid", starting_value=1))
        dag.add_edge(1, 2)
        assert _sink(ReferenceExecutor(src).execute(dag), 2)["rid"].tolist() == [1, 2, 3]

    def test_count_records(self):
        dag, src = self._read(pd.DataFrame({"v": [1, 2, 3, 4]}))
        dag.add_node(CountRecordsNode(node_id=2, output_field="n"))
        dag.add_edge(1, 2)
        assert _sink(ReferenceExecutor(src).execute(dag), 2)["n"].tolist() == [4]


class TestMultiInput:
    def test_union(self):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, table_name="a"))
        dag.add_node(ReadNode(node_id=2, table_name="b"))
        dag.add_node(UnionNode(node_id=3))
        dag.add_edge(1, 3)
        dag.add_edge(2, 3)
        src = {"a": pd.DataFrame({"v": [1, 2]}), "b": pd.DataFrame({"v": [3]})}
        assert sorted(_sink(ReferenceExecutor(src).execute(dag), 3)["v"].tolist()) == [1, 2, 3]

    def test_inner_join(self):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, table_name="l"))
        dag.add_node(ReadNode(node_id=2, table_name="r"))
        dag.add_node(JoinNode(node_id=3, join_type="inner", join_keys=[JoinKey("id", "id")]))
        dag.add_edge(1, 3, destination_anchor="Left")
        dag.add_edge(2, 3, destination_anchor="Right")
        src = {
            "l": pd.DataFrame({"id": [1, 2, 3], "x": ["a", "b", "c"]}),
            "r": pd.DataFrame({"id": [2, 3, 4], "y": [20, 30, 40]}),
        }
        out = _sink(ReferenceExecutor(src).execute(dag), 3)
        assert out["id"].tolist() == [2, 3]

    def test_left_join_keeps_unmatched(self):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, table_name="l"))
        dag.add_node(ReadNode(node_id=2, table_name="r"))
        dag.add_node(JoinNode(node_id=3, join_type="left", join_keys=[JoinKey("id", "id")]))
        dag.add_edge(1, 3, destination_anchor="Left")
        dag.add_edge(2, 3, destination_anchor="Right")
        src = {
            "l": pd.DataFrame({"id": [1, 2], "x": ["a", "b"]}),
            "r": pd.DataFrame({"id": [2], "y": [20]}),
        }
        out = _sink(ReferenceExecutor(src).execute(dag), 3)
        assert out["id"].tolist() == [1, 2]


class TestSummarize:
    def _flow(self, data, aggs):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, table_name="t"))
        dag.add_node(SummarizeNode(node_id=2, aggregations=aggs))
        dag.add_edge(1, 2)
        return _sink(ReferenceExecutor({"t": data}).execute(dag), 2)

    def test_group_by_sum(self):
        out = self._flow(
            pd.DataFrame({"g": ["a", "b", "a"], "v": [1, 2, 3]}),
            [
                AggregationField("g", AggAction.GROUP_BY),
                AggregationField("v", AggAction.SUM, "total"),
            ],
        )
        d = dict(zip(out["g"], out["total"], strict=False))
        assert d == {"a": 4, "b": 2}

    def test_multiple_aggs(self):
        out = self._flow(
            pd.DataFrame({"g": ["a", "a"], "v": [10, 30]}),
            [
                AggregationField("g", AggAction.GROUP_BY),
                AggregationField("v", AggAction.AVG, "avg_v"),
                AggregationField("v", AggAction.MAX, "max_v"),
            ],
        )
        assert out["avg_v"].tolist() == [20.0]
        assert out["max_v"].tolist() == [30]

    def test_no_group_single_row(self):
        out = self._flow(
            pd.DataFrame({"v": [1, 2, 3]}),
            [AggregationField("v", AggAction.SUM, "total")],
        )
        assert out["total"].tolist() == [6]


class TestFullPipeline:
    def test_read_filter_formula_summarize(self):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, table_name="sales"))
        dag.add_node(FilterNode(node_id=2, expression="[amount] > 100"))
        dag.add_node(FormulaNode(node_id=3, formulas=[FormulaField("tax", "[amount] * 0.1")]))
        dag.add_node(
            SummarizeNode(
                node_id=4,
                aggregations=[
                    AggregationField("region", AggAction.GROUP_BY),
                    AggregationField("amount", AggAction.SUM, "total"),
                ],
            )
        )
        dag.add_edge(1, 2)
        dag.add_edge(2, 3, origin_anchor="True")
        dag.add_edge(3, 4)
        sales = pd.DataFrame(
            {"region": ["E", "W", "E", "W", "E"], "amount": [50, 150, 200, 120, 300]}
        )
        res = ReferenceExecutor({"sales": sales}).execute(dag)
        assert res.fully_supported
        out = _sink(res, 4)
        d = dict(zip(out["region"], out["total"], strict=False))
        assert d == {"E": 500, "W": 270}
