"""Tests for join converters."""

from __future__ import annotations

from a2d.converters import ConverterRegistry
from a2d.ir.nodes import (
    AppendFieldsNode,
    FindReplaceNode,
    JoinMultipleNode,
    JoinNode,
    UnionNode,
)

from .conftest import DEFAULT_CONFIG, make_node


class TestJoinConverter:
    def test_join_inner(self):
        node = make_node(
            tool_type="Join",
            configuration={
                "JoinInfo": {
                    "Field": [
                        {"@left": "CustomerID", "@right": "CustID"},
                    ]
                }
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, JoinNode)
        assert result.join_type == "inner"
        assert len(result.join_keys) == 1
        assert result.join_keys[0].left_field == "CustomerID"
        assert result.join_keys[0].right_field == "CustID"

    def test_join_multiple_keys(self):
        node = make_node(
            tool_type="Join",
            configuration={
                "JoinInfo": {
                    "Field": [
                        {"@left": "Year", "@right": "Year"},
                        {"@left": "Month", "@right": "Month"},
                    ]
                }
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, JoinNode)
        assert len(result.join_keys) == 2

    def test_join_old_xml_format(self):
        """Old XML format uses list of JoinInfo elements with @connection and @field."""
        node = make_node(
            tool_type="Join",
            configuration={
                "JoinInfo": [
                    {"@connection": "Left", "@field": "CustomerID"},
                    {"@connection": "Right", "@field": "CustID"},
                ]
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, JoinNode)
        assert len(result.join_keys) == 1
        assert result.join_keys[0].left_field == "CustomerID"
        assert result.join_keys[0].right_field == "CustID"

    def test_join_old_xml_multiple_keys(self):
        """Old XML format with multiple join keys."""
        node = make_node(
            tool_type="Join",
            configuration={
                "JoinInfo": [
                    {"@connection": "Left", "@field": "Year"},
                    {"@connection": "Left", "@field": "Month"},
                    {"@connection": "Right", "@field": "Yr"},
                    {"@connection": "Right", "@field": "Mo"},
                ]
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, JoinNode)
        assert len(result.join_keys) == 2
        assert result.join_keys[0].left_field == "Year"
        assert result.join_keys[0].right_field == "Yr"
        assert result.join_keys[1].left_field == "Month"
        assert result.join_keys[1].right_field == "Mo"


class TestUnionConverter:
    def test_union_by_name(self):
        node = make_node(
            tool_type="Union",
            configuration={"Mode": "Auto Config by Name"},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, UnionNode)
        assert result.mode == "name"

    def test_union_by_position(self):
        node = make_node(
            tool_type="Union",
            configuration={"Mode": "Auto Config by Position"},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, UnionNode)
        assert result.mode == "position"


class TestFindReplaceConverter:
    def test_find_replace(self):
        node = make_node(
            tool_type="FindReplace",
            configuration={
                "FindField": "Status",
                "ReplaceField": "NewStatus",
                "FindMode": "Find Entire Field",
                "CaseSensitive": "False",
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, FindReplaceNode)
        assert result.find_field == "Status"
        assert result.find_mode == "exact"
        assert result.case_sensitive is False


class TestAppendFieldsConverter:
    def test_append_fields(self):
        node = make_node(tool_type="AppendFields", configuration={})
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, AppendFieldsNode)
        assert result.allow_all_appends is True


class TestJoinMultipleConverter:
    def test_join_multiple(self):
        node = make_node(
            tool_type="JoinMultiple",
            configuration={
                "JoinInfo": {
                    "Field": [
                        {"@left": "ID", "@right": "ID"},
                    ]
                },
                "JoinType": "inner",
                "InputCount": "3",
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, JoinMultipleNode)
        assert result.input_count == 3
        assert result.join_type == "inner"
