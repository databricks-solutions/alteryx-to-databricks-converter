"""Tests for ``a2d.observability.warning_categorization``.

Mirrors the behaviour of ``frontend/src/lib/warning-parsing.ts`` so the CLI
and UI agree on how to categorize and render converter warnings.
"""

from __future__ import annotations

import pytest

from a2d.observability.warning_categorization import (
    categorize_for_format,
    categorize_warnings,
    format_label,
    nodes_in_broken_components,
    parse_warning,
    parse_warnings,
)


class TestParseWarning:
    def test_unsupported_tool(self) -> None:
        w = parse_warning("Unsupported node 765: No converter for tool type: Unknown")
        assert w.kind == "unsupported_tool"
        assert w.severity == "blocker"
        assert w.node_id == 765
        assert w.tool == "Unknown"
        assert "765" in w.title
        assert "Unknown" in w.title
        assert "no converter" in w.title.lower()

    def test_unsupported_tool_with_punctuation_in_name(self) -> None:
        w = parse_warning("Unsupported node 12: No converter for tool type: AlteryxBasePluginsGui.MultiFieldFormula")
        assert w.kind == "unsupported_tool"
        assert w.tool == "AlteryxBasePluginsGui.MultiFieldFormula"
        assert w.node_id == 12

    def test_no_generator_pyspark(self) -> None:
        w = parse_warning("No PySpark generator for DynamicRenameNode (node 808)")
        assert w.kind == "missing_generator"
        assert w.severity == "review"
        assert w.node_id == 808
        assert w.tool == "DynamicRenameNode"
        assert w.generator == "pyspark"
        # Title strips "Node" suffix and uses friendly format label.
        assert "DynamicRename" in w.title
        assert "PySpark" in w.title
        assert "generator missing" in w.title

    def test_no_generator_dlt_uses_friendly_label(self) -> None:
        w = parse_warning("No DLT generator for FilterNode (node 5)")
        assert w.generator == "dlt"
        assert "Spark Declarative Pipelines" in w.title

    def test_no_generator_sql(self) -> None:
        w = parse_warning("No SQL generator for JoinNode (node 99)")
        assert w.generator == "sql"
        assert "Spark SQL" in w.title

    def test_expression_fallback(self) -> None:
        w = parse_warning("Filter expression fallback for node 679")
        assert w.kind == "expression_fallback"
        assert w.severity == "review"
        assert w.node_id == 679
        assert w.tool == "Filter"
        assert "679" in w.title
        assert "expression fallback" in w.title.lower()

    def test_sql_filter_expression_fallback(self) -> None:
        # Same shape as the real backend emits for SQL fallback (the prefix
        # word is the IR class name).
        w = parse_warning("SQL expression fallback for node 42")
        assert w.kind == "expression_fallback"
        assert w.tool == "SQL"
        assert w.node_id == 42

    def test_disconnected_components(self) -> None:
        w = parse_warning("Graph has 2 disconnected data components: [4, 14, 18], [765, 833]")
        assert w.kind == "disconnected_components"
        assert w.severity == "info"
        assert w.components == ((4, 14, 18), (765, 833))
        assert "2 disconnected" in w.title

    def test_disconnected_components_with_ellipsis_token(self) -> None:
        # Real output sometimes truncates: "[4, 14, ...], [765]"
        w = parse_warning("Graph has 2 disconnected data components: [4, 14, ...], [765]")
        assert w.kind == "disconnected_components"
        # "..." is filtered (not finite), keeping just the parseable ints.
        assert w.components == ((4, 14), (765,))

    def test_disconnected_singular(self) -> None:
        w = parse_warning("Graph has 1 disconnected data component: [1, 2, 3]")
        assert w.kind == "disconnected_components"
        assert w.components == ((1, 2, 3),)

    def test_other_falls_back_verbatim(self) -> None:
        w = parse_warning("Some completely unrecognised warning string")
        assert w.kind == "other"
        assert w.severity == "review"
        assert w.title == "Some completely unrecognised warning string"
        assert "structured template" in w.detail

    def test_dynamic_rename_dlt(self) -> None:
        w = parse_warning("DynamicRename node 808 (from-input mode): manual DLT review needed")
        assert w.kind == "missing_generator"
        assert w.severity == "review"
        assert w.node_id == 808
        assert w.tool == "DynamicRename"
        assert "808" in w.title
        assert "DynamicRename" in w.title
        assert "from-input" in w.title
        assert "manual rewrite" in w.title.lower()
        assert "data-driven" in w.detail.lower()

    def test_dynamic_rename_sql(self) -> None:
        w = parse_warning("DynamicRename node 452 (FirstRow mode): manual SQL rewrite needed")
        assert w.kind == "missing_generator"
        assert w.node_id == 452
        assert w.tool == "DynamicRename"
        assert "FirstRow" in w.title

    def test_leading_trailing_whitespace_tolerated(self) -> None:
        w = parse_warning("   Unsupported node 1: No converter for tool type: X   ")
        assert w.kind == "unsupported_tool"
        assert w.node_id == 1
        assert w.tool == "X"


class TestParseWarnings:
    def test_drops_empty_strings(self) -> None:
        out = parse_warnings(["", "  ", "Filter expression fallback for node 1"])
        assert len(out) == 1
        assert out[0].node_id == 1


class TestCategorizeWarnings:
    def test_buckets_each_kind(self) -> None:
        warnings = [
            "Unsupported node 765: No converter for tool type: Unknown",
            "No DLT generator for DynamicRenameNode (node 808)",
            "Filter expression fallback for node 679",
            "Graph has 2 disconnected data components: [4, 14], [765, 833]",
            "Random freeform warning",
        ]
        cats = categorize_warnings(parse_warnings(warnings))
        assert len(cats.unsupported) == 1
        assert len(cats.review) == 2  # missing_generator + expression_fallback
        assert len(cats.graph) == 1
        assert len(cats.other) == 1
        assert cats.total == 5
        assert cats.manual_review_node_count == 3  # nodes 765, 808, 679

    def test_dedups_node_ids_across_buckets(self) -> None:
        # Same node id appearing in unsupported AND missing_generator should
        # count once.
        warnings = [
            "Unsupported node 42: No converter for tool type: Foo",
            "No PySpark generator for FooNode (node 42)",
        ]
        cats = categorize_warnings(parse_warnings(warnings))
        assert cats.manual_review_node_count == 1

    def test_empty_input(self) -> None:
        cats = categorize_warnings([])
        assert cats.total == 0
        assert cats.manual_review_node_count == 0
        assert cats.unsupported == []
        assert cats.review == []

    def test_dynamic_rename_lands_in_review_not_other(self) -> None:
        # Regression: prior to RE_DYNAMIC_RENAME, these strings fell through
        # to the "other" bucket and were rendered verbatim. They should now
        # land in "review" (manual review needed).
        warnings = [
            "DynamicRename node 808 (from-input mode): manual DLT review needed",
            "DynamicRename node 452 (from-input mode): manual SQL rewrite needed",
            "DynamicRename node 99 (FirstRow mode): manual SQL rewrite needed",
        ]
        cats = categorize_warnings(parse_warnings(warnings))
        assert len(cats.other) == 0
        assert len(cats.review) == 3
        assert cats.manual_review_node_count == 3


class TestCategorizeForFormat:
    def test_combines_workflow_and_format_warnings(self) -> None:
        cats = categorize_for_format(
            workflow_warnings=[
                "Unsupported node 1: No converter for tool type: X",
                "Graph has 2 disconnected data components: [1, 2], [3]",
            ],
            format_warnings=["No SQL generator for FooNode (node 5)"],
        )
        assert len(cats.unsupported) == 1
        assert len(cats.review) == 1
        assert len(cats.graph) == 1


class TestNodesInBrokenComponents:
    def test_unsupported_in_disconnected_returns_full_component(self) -> None:
        parsed = parse_warnings(
            [
                "Unsupported node 765: No converter for tool type: Unknown",
                "Graph has 2 disconnected data components: [4, 14, 18], [765, 833]",
            ]
        )
        assert nodes_in_broken_components(parsed) == {765, 833}

    def test_unsupported_in_main_flow_returns_empty_when_no_components(self) -> None:
        parsed = parse_warnings(["Unsupported node 765: No converter for tool type: Unknown"])
        assert nodes_in_broken_components(parsed) == set()

    def test_components_without_unsupported_returns_empty(self) -> None:
        parsed = parse_warnings(["Graph has 2 disconnected data components: [1, 2], [3, 4]"])
        assert nodes_in_broken_components(parsed) == set()


class TestFormatLabel:
    @pytest.mark.parametrize(
        ("fmt", "expected"),
        [
            ("pyspark", "PySpark"),
            ("dlt", "Spark Declarative Pipelines"),
            ("sql", "Spark SQL"),
            ("lakeflow", "Lakeflow Designer"),
            ("unknown", "unknown"),
        ],
    )
    def test_format_label(self, fmt: str, expected: str) -> None:
        assert format_label(fmt) == expected
