"""Converter for Alteryx Tile tool -> TileNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import IRNode, TileNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class TileConverter(ToolConverter):
    """Converts Alteryx Tile tool to :class:`TileNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Tile"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        tile_count = int(safe_get(cfg, "NumTiles", safe_get(cfg, "NumTile", "4")) or "4")
        tile_field = safe_get(cfg, "TileField", safe_get(cfg, "Field", ""))
        order_field = safe_get(cfg, "OrderField", tile_field)
        output_field = safe_get(cfg, "OutputField", "Tile")

        group_fields: list[str] = []
        group_list = cfg.get("GroupFields", cfg.get("GroupBy", []))
        if isinstance(group_list, list):
            for item in group_list:
                if isinstance(item, dict):
                    group_fields.append(item.get("@field", item.get("@name", "")))
                elif isinstance(item, str):
                    group_fields.append(item)
        elif isinstance(group_list, str) and group_list:
            group_fields = [g.strip() for g in group_list.split(",") if g.strip()]

        return TileNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            tile_count=tile_count,
            tile_field=tile_field,
            group_fields=group_fields,
            order_field=order_field,
            output_field=output_field,
        )
