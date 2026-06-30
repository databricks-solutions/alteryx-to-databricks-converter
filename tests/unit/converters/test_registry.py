"""Tests for the converter registry and tool metadata."""

from __future__ import annotations

import pytest

from a2d.converters import ConverterRegistry
from a2d.ir.nodes import UnsupportedNode
from a2d.parser.schema import PLUGIN_NAME_MAP, TOOL_METADATA

from .conftest import DEFAULT_CONFIG, make_node


class TestRegistryCoverage:
    """Test that the registry is populated after importing converters."""

    def test_registry_coverage(self):
        """All non-unsupported tool types in PLUGIN_NAME_MAP should have converters registered."""
        expected_types = {
            tool_type
            for tool_type, _cat in PLUGIN_NAME_MAP.values()
            if tool_type in TOOL_METADATA and TOOL_METADATA[tool_type].conversion_method != "unsupported"
        }
        supported = ConverterRegistry.supported_tools()
        missing = expected_types - supported
        assert not missing, f"Missing converters for: {missing}"

    def test_coverage_for_returns_fraction(self):
        tool_types = {"Filter", "Formula", "Join", "SomeFakeToolThatDoesNotExist"}
        coverage = ConverterRegistry.coverage_for(tool_types)
        # 3 out of 4 should be covered
        assert coverage == pytest.approx(0.75)

    def test_coverage_for_empty_set(self):
        assert ConverterRegistry.coverage_for(set()) == 1.0


class TestUnsupportedToolFallback:
    """When no converter exists, the registry should produce UnsupportedNode."""

    def test_unsupported_tool_fallback(self):
        node = make_node(
            tool_id=999,
            tool_type="SomeNonexistentTool",
            plugin_name="com.example.FakeTool",
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, UnsupportedNode)
        assert result.node_id == 999
        assert "No converter" in result.unsupported_reason


class TestToolMetadata:
    def test_all_plugin_map_tools_have_metadata(self):
        """Every tool_type in PLUGIN_NAME_MAP should have a TOOL_METADATA entry."""
        missing = set()
        for _plugin, (tool_type, _category) in PLUGIN_NAME_MAP.items():
            if tool_type not in TOOL_METADATA:
                missing.add(tool_type)
        assert not missing, f"Missing metadata for: {missing}"

    def test_metadata_conversion_methods_valid(self):
        valid_methods = {"deterministic", "expression-engine", "template", "mapping", "stub", "unsupported"}
        for tool_type, meta in TOOL_METADATA.items():
            assert meta.conversion_method in valid_methods, f"{tool_type} has invalid method: {meta.conversion_method}"

    def test_metadata_descriptions_nonempty(self):
        for tool_type, meta in TOOL_METADATA.items():
            assert meta.short_description, f"{tool_type} has empty description"
            assert meta.databricks_equivalent, f"{tool_type} has empty databricks_equivalent"

    def test_metadata_count_matches_plugin_map(self):
        """TOOL_METADATA should cover all unique tool types from PLUGIN_NAME_MAP."""
        unique_types = {tool_type for tool_type, _cat in PLUGIN_NAME_MAP.values()}
        assert unique_types <= set(TOOL_METADATA.keys()), "TOOL_METADATA missing some PLUGIN_NAME_MAP types"


class TestAlternatePluginNames:
    """Alteryx uses multiple plugin class names for the same tool.

    Verify all known variants are mapped.
    """

    @pytest.mark.parametrize(
        "plugin_name,expected_tool_type",
        [
            # Union has two plugin names across Alteryx versions
            ("AlteryxBasePluginsGui.UnionV2.UnionV2", "Union"),
            ("AlteryxBasePluginsGui.Union.Union", "Union"),
            # Summarize appears in both base and spatial plugin namespaces
            ("AlteryxBasePluginsGui.Summarize.Summarize", "Summarize"),
            ("AlteryxSpatialPluginsGui.Summarize.Summarize", "Summarize"),
            # Interface tools with Questions. namespace
            ("AlteryxGuiToolkit.NumericUpDown.NumericUpDown", "NumericUpDown"),
            ("AlteryxGuiToolkit.Questions.NumericUpDown.NumericUpDown", "NumericUpDown"),
            ("AlteryxGuiToolkit.Questions.Tab.Tab", "Tab"),
            # Action in both namespaces
            ("AlteryxBasePluginsGui.Action.Action", "Action"),
            ("AlteryxGuiToolkit.Action.Action", "Action"),
            # New tool types
            ("AlteryxBasePluginsGui.Directory.Directory", "Directory"),
            ("AlteryxBasePluginsGui.DynamicRename.DynamicRename", "DynamicRename"),
        ],
    )
    def test_alternate_plugin_name_mapped(self, plugin_name: str, expected_tool_type: str):
        assert plugin_name in PLUGIN_NAME_MAP, f"{plugin_name} not in PLUGIN_NAME_MAP"
        tool_type, _category = PLUGIN_NAME_MAP[plugin_name]
        assert tool_type == expected_tool_type
