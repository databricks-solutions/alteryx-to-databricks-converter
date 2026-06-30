"""Converter for Alteryx Sort tool -> SortNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import ensure_list
from a2d.ir.nodes import IRNode, SortField, SortNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class SortConverter(ToolConverter):
    """Converts Alteryx Sort to :class:`SortNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Sort"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        sort_info = cfg.get("SortInfo", {})
        raw_fields = ensure_list(sort_info.get("Field", [])) if isinstance(sort_info, dict) else []

        sort_fields: list[SortField] = []
        for f in raw_fields:
            if isinstance(f, dict):
                name = f.get("@field", f.get("@name", ""))
                order = f.get("@order", "Ascending")
                ascending = order.lower() != "descending"
                # Alteryx supports NullOrder: "First" or "Last"
                null_order = str(f.get("@NullOrder", f.get("@nullOrder", "")))
                nulls_first: bool | None = None
                if null_order.lower() == "first":
                    nulls_first = True
                elif null_order.lower() == "last":
                    nulls_first = False
                sort_fields.append(SortField(field_name=str(name), ascending=ascending, nulls_first=nulls_first))

        return SortNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            sort_fields=sort_fields,
        )
