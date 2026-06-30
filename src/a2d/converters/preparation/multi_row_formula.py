"""Converter for Alteryx MultiRowFormula tool -> MultiRowFormulaNode."""

from __future__ import annotations

import html

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import ensure_list, safe_get
from a2d.ir.nodes import IRNode, MultiRowFormulaNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class MultiRowFormulaConverter(ToolConverter):
    """Converts Alteryx MultiRowFormula to :class:`MultiRowFormulaNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["MultiRowFormula"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        expression = html.unescape(safe_get(cfg, "Expression"))
        output_field = safe_get(cfg, "UpdateField") or safe_get(cfg, "OutputField")
        if not output_field:
            output_field = safe_get(cfg, "UpdateField_Name")

        rows_above_str = safe_get(cfg, "NumRows", default="1")
        rows_above = int(rows_above_str) if rows_above_str.isdigit() else 1
        rows_below = 0  # Alteryx default

        output_type = safe_get(cfg, "UpdateField_Type") or safe_get(cfg, "FieldType")
        size_str = safe_get(cfg, "UpdateField_Size")
        output_size = int(size_str) if size_str and size_str.isdigit() else None

        # Group by fields
        group_section = cfg.get("GroupFields", cfg.get("GroupByFields", {}))
        group_fields: list[str] = []
        if isinstance(group_section, dict):
            raw = ensure_list(group_section.get("Field", []))
            for f in raw:
                if isinstance(f, dict):
                    group_fields.append(f.get("@field", f.get("@name", "")))
                elif isinstance(f, str) and f:
                    group_fields.append(f)

        return MultiRowFormulaNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            expression=expression,
            output_field=output_field,
            rows_above=rows_above,
            rows_below=rows_below,
            group_fields=group_fields,
            output_type=output_type,
            output_size=output_size,
            conversion_notes=["MultiRowFormula maps to PySpark window functions (lag/lead)."],
        )
