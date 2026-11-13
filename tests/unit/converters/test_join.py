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

    @staticmethod
    def _side(conn: str, *fields: str) -> dict:
        """One <JoinInfo> as the parser reads Alteryx's own XML."""
        elems = [{"@field": f} for f in fields]
        return {"@connection": conn, "Field": elems[0] if len(elems) == 1 else elems}

    def test_join_alteryx_format_single_key(self):
        node = make_node(
            tool_type="Join",
            configuration={"JoinInfo": [self._side("Left", "CustomerID"), self._side("Right", "CustID")]},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert [(k.left_field, k.right_field) for k in result.join_keys] == [("CustomerID", "CustID")]

    def test_join_alteryx_format_composite_key(self):
        """<JoinInfo connection="Left"><Field field="A"/><Field field="B"/></JoinInfo>, per side."""
        node = make_node(
            tool_type="Join",
            configuration={
                "JoinInfo": [
                    self._side("Left", "COMPANY_ID", "ARTICLE_ID"),
                    self._side("Right", "COMPANY_ID", "ART_ID"),
                ]
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert [(k.left_field, k.right_field) for k in result.join_keys] == [
            ("COMPANY_ID", "COMPANY_ID"),
            ("ARTICLE_ID", "ART_ID"),
        ]

    def test_join_unknown_deselected(self):
        """<SelectField field="*Unknown" selected="False"/>: only listed fields come out."""
        sel = {
            "SelectConfiguration": {
                "Configuration": {
                    "@outputConnection": "Join",
                    "SelectFields": {
                        "SelectField": [
                            {"@field": "A", "@selected": "True", "@input": "Left_"},
                            {"@field": "*Unknown", "@selected": "False"},
                        ]
                    },
                }
            }
        }
        node = make_node(
            tool_type="Join", configuration={"JoinInfo": [self._side("Left", "K"), self._side("Right", "K")], **sel}
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert result.keep_unlisted is False
        assert [op.field_name for op in result.select_left] == ["A"]

    def test_join_unknown_default_keeps_unlisted(self):
        node = make_node(
            tool_type="Join", configuration={"JoinInfo": [self._side("Left", "K"), self._side("Right", "K")]}
        )
        assert ConverterRegistry.convert_node(node, DEFAULT_CONFIG).keep_unlisted is True

    def test_join_keys_that_dont_pair_up_give_no_keys(self):
        """A partial condition would join wrongly without saying so; no keys gets flagged."""
        node = make_node(
            tool_type="Join",
            configuration={"JoinInfo": [self._side("Left", "A", "B"), self._side("Right", "A")]},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert result.join_keys == []


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
    """Configuration as Alteryx saves it (keys taken from the Packt workflows)."""

    def test_find_whole_field_replace(self):
        node = make_node(
            tool_type="FindReplace",
            configuration={
                "FieldFind": "Status",
                "FieldSearch": "Code",
                "ReplaceFoundField": "NewStatus",
                "FindMode": "FindWhole",
                "NoCase": {"@value": "True"},
                "MatchWholeWord": {"@value": "False"},
                "ReplaceMode": "Replace",
                "ReplaceMultipleFound": {"@value": "False"},
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, FindReplaceNode)
        assert (result.find_field, result.search_field, result.replace_field) == ("Status", "Code", "NewStatus")
        assert result.find_mode == "exact"
        assert result.case_sensitive is False
        assert result.replace_mode == "replace"

    def test_find_any_part_append(self):
        node = make_node(
            tool_type="FindReplace",
            configuration={
                "FieldFind": "ARTICLES_KEY",
                "FieldSearch": "ARTICLES_KEY",
                "ReplaceFoundField": "DESCRIPTION",
                "FindMode": "FindAny",
                "NoCase": {"@value": "False"},
                "MatchWholeWord": {"@value": "True"},
                "ReplaceMode": "Append",
                "ReplaceMultipleFound": {"@value": "True"},
                "ReplaceAppendFields": {"Field": [{"@field": "DESCRIPTION"}, {"@field": "PRICE"}]},
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert result.find_mode == "contains"
        assert result.case_sensitive is True
        assert result.whole_word is True
        assert result.replace_mode == "append"
        assert result.replace_multiple is True
        assert result.append_fields == ["DESCRIPTION", "PRICE"]

    def test_single_append_field(self):
        node = make_node(
            tool_type="FindReplace",
            configuration={
                "FieldFind": "a",
                "FieldSearch": "b",
                "ReplaceMode": "Append",
                "ReplaceAppendFields": {"Field": {"@field": "C"}},
            },
        )
        assert ConverterRegistry.convert_node(node, DEFAULT_CONFIG).append_fields == ["C"]

    def test_unknown_find_mode_is_kept_for_the_message(self):
        node = make_node(
            tool_type="FindReplace", configuration={"FieldFind": "a", "FieldSearch": "b", "FindMode": "FindSomething"}
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert result.find_mode == "FindSomething"
        assert result.raw_find_mode == "FindSomething"


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
