"""One coverage figure: Assess (before converting) and Convert (after) agree.

Both go through the app's own services, the way the UI calls them, on every real
workflow in the Packt corpus.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from server.services.analysis import analyze_files
from server.services.conversion import convert_file

from a2d.analyzer.coverage import CoverageAnalyzer, estate_coverage_percentage
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import CommentNode, FilterNode, UnsupportedNode

PACKT = sorted((Path(__file__).parent.parent / "fixtures" / "packt").glob("*.yxmd"))


@pytest.fixture(autouse=True)
def _quiet():
    logging.disable(logging.WARNING)
    yield
    logging.disable(logging.NOTSET)


@pytest.mark.parametrize("path", PACKT, ids=lambda p: p.stem)
def test_assess_and_convert_show_the_same_coverage(path: Path) -> None:
    data = path.read_bytes()
    assessed = analyze_files([(path.name, data)])["workflows"][0]["coverage_percentage"]
    converted = convert_file(data, path.name)["coverage"]
    assert converted is not None
    assert assessed == pytest.approx(converted, abs=0.05), (assessed, converted)


def test_estate_figure_matches_business_case() -> None:
    """Assess's estate figure and the Business case's are the same number."""
    from a2d.analyzer.batch import BatchAnalyzer
    from a2d.savings import estate_facts

    files = [(p.name, p.read_bytes()) for p in PACKT[:8]]
    assessed = analyze_files(files)["avg_coverage"]
    analyses = BatchAnalyzer(expand_macros=True).analyze_files(PACKT[:8])
    assert estate_facts(analyses, {}).mean_coverage_pct == assessed


def test_containers_and_disabled_tools_are_not_counted() -> None:
    """Server_Usage_Testing has ToolContainers and a disabled container: Assess
    drops them exactly as conversion does."""
    path = next(p for p in PACKT if p.stem == "Server_Usage_Testing")
    wf = analyze_files([(path.name, path.read_bytes())])["workflows"][0]
    assert "ToolContainer" not in wf["tool_types"]
    assert "ToolContainer" not in wf["unsupported_types"]
    assert wf["tool_count"] == convert_file(path.read_bytes(), path.name)["formats"]["pyspark"]["stats"]["total_nodes"]


def test_unresolved_macros_are_named_not_a_tool_type() -> None:
    path = next(p for p in PACKT if p.stem == "World_data_prep")
    result = analyze_files([(path.name, path.read_bytes())])
    assert "Macro" not in result["unsupported_tools"]
    names = [m["name"] for m in result["unresolved_macros"]]
    assert names == ["Cleanse.yxmc"]
    assert "Cleanse.yxmc" in result["unresolved_macros"][0]["reason"]


def _dag(*nodes) -> WorkflowDAG:
    dag = WorkflowDAG()
    for n in nodes:
        dag.add_node(n)
    return dag


def test_coverage_counts_tools_not_comments_or_types() -> None:
    dag = _dag(
        FilterNode(node_id=1, original_tool_type="Filter"),
        FilterNode(node_id=2, original_tool_type="Filter"),
        FilterNode(node_id=3, original_tool_type="Filter"),
        UnsupportedNode(node_id=4, original_tool_type="MakeColumns"),
        CommentNode(node_id=5, original_tool_type="TextComment"),
    )
    report = CoverageAnalyzer().analyze_dag(dag)
    assert report.total_nodes == 4  # the comment isn't a tool
    assert report.coverage_percentage == 75.0  # 3 of 4 tools
    assert report.type_coverage_percentage == 50.0  # 1 of 2 types
    assert report.unsupported_types == {"MakeColumns"}


def test_estate_coverage_weights_by_tools() -> None:
    small = CoverageAnalyzer().analyze_dag(_dag(UnsupportedNode(node_id=1, original_tool_type="X")))
    big = CoverageAnalyzer().analyze_dag(
        _dag(*[FilterNode(node_id=i, original_tool_type="Filter") for i in range(1, 10)])
    )
    assert estate_coverage_percentage([small, big]) == 90.0
    assert estate_coverage_percentage([]) == 100.0
