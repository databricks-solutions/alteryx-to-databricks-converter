"""Converter for Alteryx Imputation tool -> ImputationNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import ImputationNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class ImputationConverter(ToolConverter):
    """Converts Alteryx Imputation tool to :class:`ImputationNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Imputation"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        fields: list[str] = []
        field_list = cfg.get("FieldList", cfg.get("Fields", []))
        if isinstance(field_list, list):
            for item in field_list:
                if isinstance(item, dict):
                    fields.append(item.get("@field", item.get("@name", "")))
                elif isinstance(item, str):
                    fields.append(item)
        elif isinstance(field_list, str):
            fields = [f.strip() for f in field_list.split(",") if f.strip()]

        method = safe_get(cfg, "Method", "mean").lower()
        custom_value = safe_get(cfg, "Value", None) or None

        return ImputationNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            fields=fields,
            method=method,
            custom_value=custom_value,
        )
