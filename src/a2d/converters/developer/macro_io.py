"""Converter for Alteryx MacroInput/MacroOutput tools -> MacroIONode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import IRNode, MacroIONode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class MacroIOConverter(ToolConverter):
    """Converts Alteryx MacroInput/MacroOutput tools to :class:`MacroIONode`.

    MacroInput and MacroOutput define the parameter boundaries for Alteryx macros.
    In Databricks, these map to notebook parameters (widgets).
    """

    @property
    def supported_tool_types(self) -> list[str]:
        return ["MacroInput", "MacroOutput"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        # Set direction based on tool type
        direction = "input" if parsed_node.tool_type == "MacroInput" else "output"

        field_name = safe_get(cfg, "FieldName", safe_get(cfg, "Name", ""))
        default_value = safe_get(cfg, "DefaultValue", safe_get(cfg, "Default", ""))
        question_text = safe_get(cfg, "QuestionText", safe_get(cfg, "Question", ""))
        data_type = safe_get(cfg, "DataType", safe_get(cfg, "Type", ""))

        return MacroIONode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            direction=direction,
            field_name=field_name,
            default_value=default_value,
            question_text=question_text,
            data_type=data_type,
            conversion_notes=[f"{parsed_node.tool_type}: macro parameters map to Databricks notebook widgets."],
        )
