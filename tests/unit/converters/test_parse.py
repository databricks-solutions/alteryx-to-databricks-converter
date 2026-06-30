"""Tests for parse converters."""

from __future__ import annotations

from a2d.converters import ConverterRegistry
from a2d.ir.nodes import (
    DateTimeNode,
    JsonParseNode,
    RegExNode,
    TextToColumnsNode,
)

from .conftest import DEFAULT_CONFIG, make_node


class TestRegExConverter:
    def test_regex_parse(self):
        node = make_node(
            tool_type="RegEx",
            configuration={
                "Field": "Address",
                "RegExExpression": "(\\d+)\\s+(.*)",
                "Mode": "ParseSimple",
                "OutputFields": {
                    "Field": [
                        {"@name": "StreetNum"},
                        {"@name": "StreetName"},
                    ]
                },
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, RegExNode)
        assert result.field_name == "Address"
        assert result.mode == "parse"
        assert result.output_fields == ["StreetNum", "StreetName"]


class TestTextToColumnsConverter:
    def test_text_to_columns(self):
        node = make_node(
            tool_type="TextToColumns",
            configuration={
                "Field": "FullName",
                "Delimiter": ",",
                "SplitTo": "Columns",
                "NumFields": "3",
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, TextToColumnsNode)
        assert result.field_name == "FullName"
        assert result.delimiter == ","
        assert result.split_to == "columns"
        assert result.num_columns == 3


class TestDateTimeConverter:
    def test_datetime_parse(self):
        node = make_node(
            tool_type="DateTime",
            configuration={
                "InputField": "DateStr",
                "OutputField": "ParsedDate",
                "ConversionMode": "DateTimeParse",
                "FormatString": "%Y-%m-%d",
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, DateTimeNode)
        assert result.input_field == "DateStr"
        assert result.output_field == "ParsedDate"
        assert result.conversion_mode == "parse"
        assert result.format_string == "%Y-%m-%d"


class TestJsonParseConverter:
    def test_json_parse(self):
        node = make_node(
            tool_type="JsonParse",
            configuration={
                "Field": "JsonPayload",
                "OutputField": "Parsed",
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, JsonParseNode)
        assert result.input_field == "JsonPayload"
        assert result.output_field == "Parsed"
