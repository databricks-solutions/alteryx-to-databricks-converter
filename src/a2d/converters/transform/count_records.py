"""Converter for Alteryx CountRecords tool -> CountRecordsNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import CountRecordsNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class CountRecordsConverter(ToolConverter):
    """Converts Alteryx CountRecords to :class:`CountRecordsNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["CountRecords"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        output_field = safe_get(cfg, "FieldName", default="Count")
        if not output_field:
            output_field = "Count"

        return CountRecordsNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            output_field=output_field,
        )
