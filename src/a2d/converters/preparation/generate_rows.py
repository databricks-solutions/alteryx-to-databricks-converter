"""Converter for Alteryx GenerateRows tool -> GenerateRowsNode."""

from __future__ import annotations

import html

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import GenerateRowsNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class GenerateRowsConverter(ToolConverter):
    """Converts Alteryx GenerateRows to :class:`GenerateRowsNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["GenerateRows"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        init_expression = html.unescape(safe_get(cfg, "InitExpression"))
        condition_expression = html.unescape(safe_get(cfg, "ConditionExpression"))
        loop_expression = html.unescape(safe_get(cfg, "LoopExpression"))
        output_field = safe_get(cfg, "FieldName") or safe_get(cfg, "OutputField")
        output_type = safe_get(cfg, "FieldType", default="Int64") or "Int64"

        return GenerateRowsNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            init_expression=init_expression,
            condition_expression=condition_expression,
            loop_expression=loop_expression,
            output_field=output_field,
            output_type=output_type,
            conversion_notes=["GenerateRows maps to Spark range() or recursive DataFrame generation."],
        )
