"""Converter for Alteryx CreatePoints tool -> CreatePointsNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import CreatePointsNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class CreatePointsConverter(ToolConverter):
    """Converts Alteryx CreatePoints tool to :class:`CreatePointsNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["CreatePoints"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        lat_field = safe_get(cfg, "LatitudeField", "Latitude")
        lon_field = safe_get(cfg, "LongitudeField", "Longitude")
        output_field = safe_get(cfg, "OutputField", "SpatialObj")

        return CreatePointsNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            lat_field=lat_field,
            lon_field=lon_field,
            output_field=output_field,
            conversion_confidence=0.8,
            conversion_method="mapping",
            conversion_notes=[
                "Creates struct(lat, lon) column; use Mosaic st_point for full spatial support.",
            ],
        )
