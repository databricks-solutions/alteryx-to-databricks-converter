"""Converter for Alteryx MultiFieldFormula tool -> MultiFieldFormulaNode."""

from __future__ import annotations

import html

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import ensure_list, safe_get
from a2d.ir.nodes import IRNode, MultiFieldFormulaNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class MultiFieldFormulaConverter(ToolConverter):
    """Converts Alteryx MultiFieldFormula to :class:`MultiFieldFormulaNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["MultiFieldFormula"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        expression = html.unescape(safe_get(cfg, "Expression"))
        output_type = safe_get(cfg, "FieldType") or safe_get(cfg, "OutputType")
        copy_output = safe_get(cfg, "CopyOutput", default="False").lower() == "true"

        # Fields the formula is applied to
        fields_section = cfg.get("Fields", cfg.get("FieldList", {}))
        fields: list[str] = []
        if isinstance(fields_section, dict):
            raw = ensure_list(fields_section.get("Field", []))
            for f in raw:
                if isinstance(f, dict):
                    fields.append(f.get("@field", f.get("@name", "")))
                elif isinstance(f, str) and f:
                    fields.append(f)
        elif isinstance(fields_section, str) and fields_section:
            # Comma-separated field list
            fields = [f.strip() for f in fields_section.split(",") if f.strip()]

        return MultiFieldFormulaNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            expression=expression,
            fields=fields,
            output_type=output_type,
            copy_output=copy_output,
        )
