"""Converter for Alteryx Directory tool -> DirectoryNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get, safe_get_nested
from a2d.ir.nodes import DirectoryNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class DirectoryConverter(ToolConverter):
    """Converts Alteryx Directory tool to :class:`DirectoryNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Directory"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        directory_path = safe_get(cfg, "Directory", "")
        file_pattern = safe_get(cfg, "FileSpec", "*")
        include_subdirs = safe_get_nested(cfg, "IncludeSubDirs", "@value", default="False").lower() == "true"

        return DirectoryNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            directory_path=directory_path,
            file_pattern=file_pattern,
            include_subdirs=include_subdirs,
            conversion_notes=["Directory tool maps to dbutils.fs.ls() in Databricks."],
        )
