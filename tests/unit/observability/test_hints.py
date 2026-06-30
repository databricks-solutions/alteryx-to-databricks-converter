"""Tests for the remediation hints module."""

from __future__ import annotations

from a2d.observability.hints import enrich_warnings, get_hint


class TestGetHint:
    def test_spatial_match(self):
        hint = get_hint("Unsupported tool: SpatialMatch")
        assert hint is not None
        assert "Mosaic" in hint[0]
        assert hint[1] == "spatial"

    def test_expression_placeholder(self):
        hint = get_hint("PLACEHOLDER in formula for 'col1'")
        assert hint is not None
        assert "PLACEHOLDER" in hint[0]
        assert hint[1] == "expression"

    def test_no_join_keys(self):
        hint = get_hint("Join node 5: no join keys found — manual condition required")
        assert hint is not None
        assert hint[1] == "join"

    def test_unknown_function(self):
        hint = get_hint("Unknown function: Soundex")
        assert hint is not None
        assert hint[1] == "expression"

    def test_no_match(self):
        hint = get_hint("Some random warning with no pattern match at all")
        assert hint is None

    def test_case_insensitive_match(self):
        hint = get_hint("UNSUPPORTED TOOL: Something")
        assert hint is not None
        assert hint[1] == "unsupported"

    def test_predictive_hint(self):
        hint = get_hint("DecisionTree (node 5): requires manual conversion to Spark MLlib")
        assert hint is not None
        assert hint[1] == "predictive"


class TestEnrichWarnings:
    def test_enriches_warnings(self):
        warnings = [
            "Unsupported tool: SpatialMatch",
            "Something random",
            "Unknown function: CustomFunc",
        ]
        enriched = enrich_warnings(warnings)

        assert len(enriched) == 3
        assert enriched[0]["hint"] is not None
        assert enriched[0]["category"] == "spatial"
        assert enriched[1]["hint"] is None
        assert enriched[1]["category"] is None
        assert enriched[2]["hint"] is not None
        assert enriched[2]["category"] == "expression"

    def test_empty_list(self):
        assert enrich_warnings([]) == []
