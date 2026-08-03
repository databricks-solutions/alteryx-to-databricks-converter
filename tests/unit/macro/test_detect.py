"""Tests for macro-call detection and identifier derivation."""

from __future__ import annotations

from a2d.macro.detect import (
    find_macro_calls,
    function_name_for,
    macro_path_for_node,
)
from a2d.parser.schema import ParsedNode, ParsedWorkflow


def _node(tool_id, plugin_name="", tool_type="", config=None, disabled=False):
    return ParsedNode(
        tool_id=tool_id,
        plugin_name=plugin_name,
        tool_type=tool_type,
        category="",
        configuration=config or {},
        disabled=disabled,
    )


class TestMacroPathForNode:
    def test_explicit_macro_path(self):
        node = _node(1, "CustomGui.Foo", "Unknown", {"MacroPath": "macros/Clean.yxmc"})
        assert macro_path_for_node(node) == "macros/Clean.yxmc"

    def test_macro_path_dict_text(self):
        node = _node(1, config={"MacroPath": {"#text": "m/a.yxmc"}})
        assert macro_path_for_node(node) == "m/a.yxmc"

    def test_engine_settings_plugin_prefix(self):
        node = _node(1, plugin_name="macro:helper.yxmc", tool_type="Helper")
        assert macro_path_for_node(node) == "helper.yxmc"

    def test_boundary_tools_excluded(self):
        node = _node(1, "AlteryxBasePluginsGui.MacroInput.MacroInput", "MacroInput", {"MacroPath": "x.yxmc"})
        assert macro_path_for_node(node) is None

    def test_non_macro_returns_none(self):
        node = _node(1, "AlteryxBasePluginsGui.Filter.Filter", "Filter")
        assert macro_path_for_node(node) is None


class TestFindMacroCalls:
    def test_finds_and_sorts_by_id(self):
        wf = ParsedWorkflow(
            file_path="w.yxmd",
            alteryx_version="2023.1",
            nodes=[
                _node(3, config={"MacroPath": "b.yxmc"}),
                _node(1, config={"MacroPath": "a.yxmc"}),
                _node(2, "AlteryxBasePluginsGui.Filter.Filter", "Filter"),
            ],
        )
        calls = find_macro_calls(wf)
        assert [c.node_id for c in calls] == [1, 3]
        assert [c.macro_path for c in calls] == ["a.yxmc", "b.yxmc"]

    def test_disabled_call_skipped(self):
        wf = ParsedWorkflow(
            file_path="w.yxmd",
            alteryx_version="2023.1",
            nodes=[_node(1, config={"MacroPath": "a.yxmc"}, disabled=True)],
        )
        assert find_macro_calls(wf) == []


class TestFunctionNameFor:
    def test_basic(self):
        assert function_name_for("macros/StandardCleanse.yxmc") == "macro_standardcleanse"

    def test_spaces_and_punctuation(self):
        assert function_name_for("My Macro (v2).yxmc") == "macro_my_macro_v2"

    def test_windows_path(self):
        assert function_name_for("C:\\macros\\Clean.yxmc") == "macro_clean"

    def test_leading_digit(self):
        assert function_name_for("123.yxmc").startswith("macro_")

    def test_no_double_macro_prefix(self):
        assert function_name_for("MacroThing.yxmc") == "macrothing"
