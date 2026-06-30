"""Converter for Alteryx RecordID tool -> RecordIDNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import IRNode, RecordIDNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class RecordIDConverter(ToolConverter):
    """Converts Alteryx RecordID to :class:`RecordIDNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["RecordID"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        output_field = safe_get(cfg, "FieldName", default="RecordID") or "RecordID"

        starting_str = safe_get(cfg, "StartValue", default="1")
        starting_value = int(starting_str) if starting_str.isdigit() else 1

        output_type = safe_get(cfg, "FieldType", default="Int64") or "Int64"

        return RecordIDNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            output_field=output_field,
            starting_value=starting_value,
            output_type=output_type,
        )
