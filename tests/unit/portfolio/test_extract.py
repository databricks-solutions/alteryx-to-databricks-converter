"""Tests for portfolio artifact extraction."""

from __future__ import annotations

from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    DynamicInputNode,
    DynamicOutputNode,
    FilterNode,
    ReadNode,
    WriteNode,
)
from a2d.portfolio.extract import extract_artifacts, normalize_artifact


class TestNormalizeArtifact:
    def test_lowercases_and_unifies_separators(self):
        assert normalize_artifact("C:\\Data\\Sales.csv") == "c:/data/sales.csv"

    def test_strips_quotes_and_whitespace(self):
        assert normalize_artifact("  'my/table'  ") == "my/table"

    def test_strips_trailing_slash(self):
        assert normalize_artifact("dir/") == "dir"

    def test_empty(self):
        assert normalize_artifact("") == ""
        assert normalize_artifact(None) == ""  # type: ignore[arg-type]


def _dag(*nodes):
    dag = WorkflowDAG()
    for n in nodes:
        dag.add_node(n)
    return dag


class TestExtractArtifacts:
    def test_reads_and_writes_collected(self):
        dag = _dag(
            ReadNode(node_id=1, original_tool_type="Input", file_path="in/RAW.csv"),
            WriteNode(node_id=2, original_tool_type="Output", file_path="out/clean.csv"),
        )
        arts = extract_artifacts("wf", "wf.yxmd", dag, [])
        assert arts.reads == {"in/raw.csv"}
        assert arts.writes == {"out/clean.csv"}

    def test_table_name_preferred_over_path(self):
        dag = _dag(ReadNode(node_id=1, table_name="catalog.schema.tbl", file_path="ignored.csv"))
        arts = extract_artifacts("wf", "wf.yxmd", dag, [])
        assert arts.reads == {"catalog.schema.tbl"}

    def test_dynamic_nodes(self):
        dag = _dag(
            DynamicInputNode(node_id=1, file_path_pattern="glob/*.csv"),
            DynamicOutputNode(node_id=2, file_path_expression="out/[Region].csv"),
        )
        arts = extract_artifacts("wf", "wf.yxmd", dag, [])
        assert arts.reads == {"glob/*.csv"}
        assert arts.writes == {"out/[region].csv"}

    def test_macros_normalized_and_deduped(self):
        dag = _dag(ReadNode(node_id=1, file_path="a.csv"))
        arts = extract_artifacts("wf", "wf.yxmd", dag, ["Macros/Clean.yxmc", "macros/clean.yxmc"])
        assert arts.macros == {"macros/clean.yxmc"}

    def test_subflow_fingerprint_skips_trivial(self):
        # Single node component is below the min-size threshold.
        dag = _dag(ReadNode(node_id=1, file_path="a.csv"))
        arts = extract_artifacts("wf", "wf.yxmd", dag, [])
        assert arts.subflow_fingerprints == {}

    def test_subflow_fingerprint_for_connected_component(self):
        dag = _dag(
            ReadNode(node_id=1, original_tool_type="Input", file_path="a.csv"),
            FilterNode(node_id=2, original_tool_type="Filter", expression="[x] > 1"),
            WriteNode(node_id=3, original_tool_type="Output", file_path="b.csv"),
        )
        dag.add_edge(1, 2)
        dag.add_edge(2, 3)
        arts = extract_artifacts("wf", "wf.yxmd", dag, [])
        assert len(arts.subflow_fingerprints) == 1
        (desc,) = arts.subflow_fingerprints.values()
        assert "Filter" in desc and "Input" in desc and "Output" in desc

    def test_identical_structure_same_fingerprint(self):
        def make():
            d = _dag(
                ReadNode(node_id=1, original_tool_type="Input", file_path="x.csv"),
                FilterNode(node_id=2, original_tool_type="Filter", expression="[a]=1"),
                WriteNode(node_id=3, original_tool_type="Output", file_path="y.csv"),
            )
            d.add_edge(1, 2)
            d.add_edge(2, 3)
            return d

        a = extract_artifacts("a", "a.yxmd", make(), [])
        b = extract_artifacts("b", "b.yxmd", make(), [])
        assert set(a.subflow_fingerprints) == set(b.subflow_fingerprints)
