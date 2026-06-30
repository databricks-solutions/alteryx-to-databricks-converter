"""Converter for Alteryx Browse (BrowseV2) tool -> BrowseNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.ir.nodes import BrowseNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class BrowseConverter(ToolConverter):
    """Converts Alteryx Browse (BrowseV2) to :class:`BrowseNode`.

    Browse is a display-only tool.  In Databricks it maps to
    ``df.display()`` or is simply omitted.
    """

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Browse"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        return BrowseNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            conversion_notes=["Browse tool maps to display() in Databricks or can be omitted."],
        )
