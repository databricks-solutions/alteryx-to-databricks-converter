"""Converter for Alteryx AutoField tool -> AutoFieldNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.ir.nodes import AutoFieldNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class AutoFieldConverter(ToolConverter):
    """Converts Alteryx AutoField to :class:`AutoFieldNode`.

    AutoField automatically sizes fields to their minimum required size.
    In Spark/Databricks there is no direct equivalent, so this becomes a
    passthrough.
    """

    @property
    def supported_tool_types(self) -> list[str]:
        return ["AutoField"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        return AutoFieldNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            conversion_notes=["AutoField is a no-op in Spark; field sizes are handled automatically."],
        )
