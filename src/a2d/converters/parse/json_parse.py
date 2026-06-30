"""Converter for Alteryx JsonParse tool -> JsonParseNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import IRNode, JsonParseNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class JsonParseConverter(ToolConverter):
    """Converts Alteryx JsonParse to :class:`JsonParseNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["JsonParse"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        input_field = safe_get(cfg, "Field") or safe_get(cfg, "JSONField")
        output_field = safe_get(cfg, "OutputField")
        flatten_mode = safe_get(cfg, "FlattenMode", default="auto").lower()
        if flatten_mode not in ("auto", "keys", "values"):
            flatten_mode = "auto"

        return JsonParseNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            input_field=input_field,
            output_field=output_field,
            flatten_mode=flatten_mode,
        )
