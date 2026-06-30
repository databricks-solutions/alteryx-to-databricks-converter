"""Tests for developer converters."""

from __future__ import annotations

from a2d.converters import ConverterRegistry
from a2d.ir.nodes import DownloadNode, PythonToolNode, RunCommandNode

from .conftest import DEFAULT_CONFIG, make_node


class TestPythonToolConverter:
    def test_python_tool(self):
        node = make_node(
            tool_type="PythonTool",
            configuration={"Code": "from ayx import Alteryx\ndf = Alteryx.read('#1')"},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, PythonToolNode)
        assert "Alteryx" in result.code
        assert result.conversion_confidence < 0.5


class TestDownloadConverter:
    def test_download(self):
        node = make_node(
            tool_type="Download",
            configuration={
                "URL": "https://api.example.com/data",
                "Method": "GET",
                "OutputField": "Response",
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, DownloadNode)
        assert result.url_static == "https://api.example.com/data"
        assert result.method == "GET"
        assert result.output_field == "Response"
        assert result.conversion_confidence < 0.5


class TestRunCommandConverter:
    def test_run_command(self):
        node = make_node(
            tool_type="RunCommand",
            configuration={
                "Command": "python",
                "Arguments": "script.py --input data.csv",
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, RunCommandNode)
        assert result.command == "python"
        assert result.command_arguments == "script.py --input data.csv"
        assert result.conversion_confidence < 0.3
