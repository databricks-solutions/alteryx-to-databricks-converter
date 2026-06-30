"""Converter for Alteryx Formula tool -> FormulaNode."""

from __future__ import annotations

import html

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import ensure_list, safe_get
from a2d.ir.nodes import FormulaField, FormulaNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class FormulaConverter(ToolConverter):
    """Converts Alteryx Formula to :class:`FormulaNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Formula"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        # FormulaFields -> FormulaField  (list of dicts)
        formula_fields_section = cfg.get("FormulaFields", {})
        if isinstance(formula_fields_section, dict):
            raw_fields = ensure_list(formula_fields_section.get("FormulaField", []))
        else:
            raw_fields = ensure_list(formula_fields_section)

        formulas: list[FormulaField] = []
        for f in raw_fields:
            if isinstance(f, dict):
                output_field = safe_get(f, "@field") or safe_get(f, "@expression_OutputFieldName")
                expression = safe_get(f, "@expression") or safe_get(f, "#text")
                data_type = safe_get(f, "@type")
                size_str = safe_get(f, "@size")
                size = int(size_str) if size_str and size_str.isdigit() else None

                # HTML-decode the expression (Alteryx encodes &gt; etc.)
                expression = html.unescape(expression)

                formulas.append(
                    FormulaField(
                        output_field=output_field,
                        expression=expression,
                        data_type=data_type,
                        size=size,
                    )
                )

        return FormulaNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            formulas=formulas,
        )
