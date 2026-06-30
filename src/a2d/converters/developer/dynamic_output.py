"""Converter for Alteryx DynamicOutput tool -> DynamicOutputNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import DynamicOutputNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class DynamicOutputConverter(ToolConverter):
    """Converts Alteryx DynamicOutput tool to :class:`DynamicOutputNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["DynamicOutput"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        file_path_expression = safe_get(cfg, "FilePath", safe_get(cfg, "PathField", ""))
        file_format = safe_get(cfg, "FileFormat", "csv").lower()
        partition_field = safe_get(cfg, "PartitionField", safe_get(cfg, "GroupField", ""))

        return DynamicOutputNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            file_path_expression=file_path_expression,
            file_format=file_format,
            partition_field=partition_field,
            conversion_notes=["DynamicOutput: output path expressions may need Databricks adjustment."],
        )
