"""Tests for IO converters (Input, Output, TextInput, Browse)."""

from __future__ import annotations

from a2d.converters import ConverterRegistry
from a2d.ir.nodes import BrowseNode, DirectoryNode, LiteralDataNode, ReadNode, WriteNode

from .conftest import DEFAULT_CONFIG, make_node


class TestInputDataConverter:
    def test_input_data_csv(self):
        node = make_node(
            tool_type="Input",
            configuration={
                "File": "C:\\data\\sales.csv",
                "HeaderRow": "True",
                "Delimiter": ",",
                "CodePage": "utf-8",
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, ReadNode)
        assert result.source_type == "file"
        assert result.file_path == "C:\\data\\sales.csv"
        assert result.file_format == "csv"
        assert result.has_header is True
        assert result.delimiter == ","
        assert result.encoding == "utf-8"

    def test_input_data_xlsx(self):
        node = make_node(
            tool_type="Input",
            configuration={"File": "data/report.xlsx"},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, ReadNode)
        assert result.file_format == "xlsx"

    def test_input_data_database(self):
        node = make_node(
            tool_type="Input",
            configuration={
                "Connection": "odbc:DSN=MyDB",
                "TableName": "customers",
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, ReadNode)
        assert result.source_type == "database"
        assert result.table_name == "customers"
        assert result.conversion_confidence < 1.0


class TestOutputDataConverter:
    def test_output_data_csv(self):
        node = make_node(
            tool_type="Output",
            configuration={
                "File": "C:\\output\\results.csv",
                "Mode": "Overwrite",
                "HeaderRow": "True",
                "Delimiter": "|",
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, WriteNode)
        assert result.destination_type == "file"
        assert result.file_format == "csv"
        assert result.write_mode == "overwrite"
        assert result.delimiter == "|"

    def test_output_data_append_mode(self):
        node = make_node(
            tool_type="Output",
            configuration={
                "File": "output.csv",
                "Mode": "Append",
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, WriteNode)
        assert result.write_mode == "append"


class TestTextInputConverter:
    def test_text_input_with_data(self):
        node = make_node(
            tool_type="TextInput",
            configuration={
                "Fields": {
                    "Field": [
                        {"@name": "Name", "@type": "V_WString"},
                        {"@name": "Age", "@type": "Int32"},
                    ]
                },
                "Data": {
                    "r": [
                        {"c": ["Alice", "30"]},
                        {"c": ["Bob", "25"]},
                    ]
                },
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, LiteralDataNode)
        assert result.num_fields == 2
        assert result.num_records == 2
        assert result.field_names == ["Name", "Age"]
        assert result.field_types == ["V_WString", "Int32"]
        assert result.data_rows == [["Alice", "30"], ["Bob", "25"]]

    def test_text_input_empty(self):
        node = make_node(tool_type="TextInput", configuration={})
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, LiteralDataNode)
        assert result.num_fields == 0
        assert result.num_records == 0


class TestDirectoryConverter:
    def test_directory_basic(self):
        node = make_node(
            tool_type="Directory",
            configuration={
                "Directory": "C:\\data\\files",
                "FileSpec": "*.csv",
                "IncludeSubDirs": {"@value": "False"},
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, DirectoryNode)
        assert result.directory_path == "C:\\data\\files"
        assert result.file_pattern == "*.csv"
        assert result.include_subdirs is False

    def test_directory_with_subdirs(self):
        node = make_node(
            tool_type="Directory",
            configuration={
                "Directory": "/mnt/data",
                "FileSpec": "*.*",
                "IncludeSubDirs": {"@value": "True"},
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, DirectoryNode)
        assert result.include_subdirs is True

    def test_directory_defaults(self):
        node = make_node(tool_type="Directory", configuration={})
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, DirectoryNode)
        assert result.directory_path == ""
        assert result.file_pattern == "*"
        assert result.include_subdirs is False


class TestBrowseConverter:
    def test_browse(self):
        node = make_node(tool_type="Browse")
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, BrowseNode)
