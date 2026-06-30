"""Converter for Alteryx TradeArea tool -> TradeAreaNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import IRNode, TradeAreaNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class TradeAreaConverter(ToolConverter):
    """Converts Alteryx TradeArea tool to :class:`TradeAreaNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["TradeArea"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        input_field = safe_get(cfg, "InputField", "SpatialObj")
        radius = float(safe_get(cfg, "Radius", "1") or "1")
        units = safe_get(cfg, "RadiusUnits", "Miles").lower()
        ring_count = int(safe_get(cfg, "NumberOfRings", "1") or "1")

        return TradeAreaNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            input_field=input_field,
            radius=radius,
            radius_units=units,
            ring_count=ring_count,
            conversion_confidence=0.5,
            conversion_method="mapping",
            conversion_notes=[
                "Uses Mosaic st_buffer or H3 k-ring for trade area generation.",
                "Concentric ring support requires multiple buffer operations.",
            ],
        )
