"""Unit tests for the Alteryx workflow parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from a2d.parser.workflow_parser import WorkflowParser

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "workflows"


@pytest.fixture
def parser() -> WorkflowParser:
    return WorkflowParser()


# ---------------------------------------------------------------------------
# Test: simple_filter.yxmd
# ---------------------------------------------------------------------------


class TestParseSimpleFilter:
    """Parse the simple_filter fixture and verify structure."""

    def test_node_count(self, parser: WorkflowParser) -> None:
        wf = parser.parse(FIXTURES_DIR / "simple_filter.yxmd")
        assert len(wf.nodes) == 4

    def test_connection_count(self, parser: WorkflowParser) -> None:
        wf = parser.parse(FIXTURES_DIR / "simple_filter.yxmd")
        assert len(wf.connections) == 3

    def test_tool_types(self, parser: WorkflowParser) -> None:
        wf = parser.parse(FIXTURES_DIR / "simple_filter.yxmd")
        types = {n.tool_type for n in wf.nodes}
        assert "TextInput" in types
        assert "Filter" in types
        assert "Output" in types

    def test_version(self, parser: WorkflowParser) -> None:
        wf = parser.parse(FIXTURES_DIR / "simple_filter.yxmd")
        assert wf.alteryx_version == "2023.1"

    def test_filter_annotation(self, parser: WorkflowParser) -> None:
        wf = parser.parse(FIXTURES_DIR / "simple_filter.yxmd")
        filter_node = next(n for n in wf.nodes if n.tool_type == "Filter")
        assert filter_node.annotation == "Filter Age > 25"

    def test_connection_anchors(self, parser: WorkflowParser) -> None:
        wf = parser.parse(FIXTURES_DIR / "simple_filter.yxmd")
        # Filter True branch -> ToolID 3
        true_conn = next(c for c in wf.connections if c.origin.tool_id == 2 and c.origin.anchor_name == "True")
        assert true_conn.destination.tool_id == 3

        # Filter False branch -> ToolID 4
        false_conn = next(c for c in wf.connections if c.origin.tool_id == 2 and c.origin.anchor_name == "False")
        assert false_conn.destination.tool_id == 4


# ---------------------------------------------------------------------------
# Test: join_and_summarize.yxmd
# ---------------------------------------------------------------------------


class TestParseJoinSummarize:
    """Parse the join_and_summarize fixture and verify structure."""

    def test_node_count(self, parser: WorkflowParser) -> None:
        wf = parser.parse(FIXTURES_DIR / "join_and_summarize.yxmd")
        assert len(wf.nodes) == 5

    def test_connection_count(self, parser: WorkflowParser) -> None:
        wf = parser.parse(FIXTURES_DIR / "join_and_summarize.yxmd")
        assert len(wf.connections) == 4

    def test_join_node(self, parser: WorkflowParser) -> None:
        wf = parser.parse(FIXTURES_DIR / "join_and_summarize.yxmd")
        join_node = next(n for n in wf.nodes if n.tool_type == "Join")
        assert join_node.tool_id == 3
        assert join_node.category == "join"

    def test_summarize_node(self, parser: WorkflowParser) -> None:
        wf = parser.parse(FIXTURES_DIR / "join_and_summarize.yxmd")
        summarize_node = next(n for n in wf.nodes if n.tool_type == "Summarize")
        assert summarize_node.tool_id == 4
        assert summarize_node.category == "transform"

    def test_join_has_two_inputs(self, parser: WorkflowParser) -> None:
        wf = parser.parse(FIXTURES_DIR / "join_and_summarize.yxmd")
        join_inputs = [c for c in wf.connections if c.destination.tool_id == 3]
        assert len(join_inputs) == 2
        anchors = {c.destination.anchor_name for c in join_inputs}
        assert "Left" in anchors
        assert "Right" in anchors


# ---------------------------------------------------------------------------
# Test: parse_string
# ---------------------------------------------------------------------------


class TestParseString:
    """Test the parse_string convenience method."""

    MINIMAL_XML = """<?xml version="1.0"?>
    <AlteryxDocument yxmdVer="2024.1">
      <Nodes>
        <Node ToolID="10">
          <GuiSettings Plugin="AlteryxBasePluginsGui.BrowseV2.BrowseV2">
            <Position x="42" y="84"/>
          </GuiSettings>
          <Properties>
            <Configuration/>
            <Annotation DisplayMode="0">
              <Name>My Browse</Name>
            </Annotation>
          </Properties>
        </Node>
      </Nodes>
      <Connections/>
      <Properties/>
    </AlteryxDocument>
    """

    def test_parse_string_basic(self, parser: WorkflowParser) -> None:
        wf = parser.parse_string(self.MINIMAL_XML)
        assert len(wf.nodes) == 1
        assert wf.nodes[0].tool_id == 10
        assert wf.nodes[0].tool_type == "Browse"
        assert wf.nodes[0].annotation == "My Browse"
        assert wf.alteryx_version == "2024.1"

    def test_parse_string_file_path(self, parser: WorkflowParser) -> None:
        wf = parser.parse_string(self.MINIMAL_XML, file_path="test.yxmd")
        assert wf.file_path == "test.yxmd"

    def test_parse_string_default_file_path(self, parser: WorkflowParser) -> None:
        wf = parser.parse_string(self.MINIMAL_XML)
        assert wf.file_path == "<string>"

    def test_parse_string_position(self, parser: WorkflowParser) -> None:
        wf = parser.parse_string(self.MINIMAL_XML)
        assert wf.nodes[0].position == (42.0, 84.0)


# ---------------------------------------------------------------------------
# Test: unknown plugin handling
# ---------------------------------------------------------------------------


class TestUnknownPlugin:
    """Verify graceful handling of unrecognised Alteryx plugins."""

    UNKNOWN_XML = """<?xml version="1.0"?>
    <AlteryxDocument yxmdVer="2023.1">
      <Nodes>
        <Node ToolID="99">
          <GuiSettings Plugin="SomeVendor.CustomTool.CustomTool">
            <Position x="0" y="0"/>
          </GuiSettings>
          <Properties>
            <Configuration>
              <CustomSetting>value</CustomSetting>
            </Configuration>
          </Properties>
        </Node>
      </Nodes>
      <Connections/>
      <Properties/>
    </AlteryxDocument>
    """

    def test_unknown_plugin_yields_unknown_type(self, parser: WorkflowParser) -> None:
        wf = parser.parse_string(self.UNKNOWN_XML)
        assert wf.nodes[0].tool_type == "Unknown"
        assert wf.nodes[0].category == "unknown"

    def test_unknown_plugin_preserves_plugin_name(self, parser: WorkflowParser) -> None:
        wf = parser.parse_string(self.UNKNOWN_XML)
        assert wf.nodes[0].plugin_name == "SomeVendor.CustomTool.CustomTool"

    def test_unknown_plugin_still_has_configuration(self, parser: WorkflowParser) -> None:
        wf = parser.parse_string(self.UNKNOWN_XML)
        assert wf.nodes[0].configuration.get("CustomSetting") == "value"


# ---------------------------------------------------------------------------
# Test: node configuration extraction
# ---------------------------------------------------------------------------


class TestNodeConfiguration:
    """Verify that configuration dicts are correctly extracted."""

    def test_filter_expression(self, parser: WorkflowParser) -> None:
        wf = parser.parse(FIXTURES_DIR / "simple_filter.yxmd")
        filter_node = next(n for n in wf.nodes if n.tool_type == "Filter")
        # The expression text should be captured
        assert "Expression" in filter_node.configuration
        assert "> 25" in filter_node.configuration["Expression"]

    def test_filter_mode(self, parser: WorkflowParser) -> None:
        wf = parser.parse(FIXTURES_DIR / "simple_filter.yxmd")
        filter_node = next(n for n in wf.nodes if n.tool_type == "Filter")
        assert filter_node.configuration.get("Mode") == "Simple"

    def test_complex_pipeline_formula_config(self, parser: WorkflowParser) -> None:
        wf = parser.parse(FIXTURES_DIR / "complex_pipeline.yxmd")
        formula_node = next(n for n in wf.nodes if n.tool_type == "Formula")
        assert "FormulaFields" in formula_node.configuration

    def test_raw_xml_preserved(self, parser: WorkflowParser) -> None:
        wf = parser.parse(FIXTURES_DIR / "simple_filter.yxmd")
        for node in wf.nodes:
            assert node.raw_xml is not None
            assert "ToolID" in node.raw_xml

    def test_no_macro_references(self, parser: WorkflowParser) -> None:
        """None of the test fixtures contain macro references."""
        wf = parser.parse(FIXTURES_DIR / "simple_filter.yxmd")
        assert wf.macro_references == []


# ---------------------------------------------------------------------------
# Test: file not found
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case handling."""

    def test_file_not_found(self, parser: WorkflowParser) -> None:
        with pytest.raises(FileNotFoundError):
            parser.parse(Path("/nonexistent/workflow.yxmd"))

    def test_empty_connections(self, parser: WorkflowParser) -> None:
        xml = """<?xml version="1.0"?>
        <AlteryxDocument yxmdVer="2023.1">
          <Nodes/>
          <Connections/>
          <Properties/>
        </AlteryxDocument>
        """
        wf = parser.parse_string(xml)
        assert len(wf.nodes) == 0
        assert len(wf.connections) == 0
