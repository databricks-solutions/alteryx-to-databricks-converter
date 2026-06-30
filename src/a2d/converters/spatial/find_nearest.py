"""Converter for Alteryx FindNearest tool -> FindNearestNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import FindNearestNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class FindNearestConverter(ToolConverter):
    """Converts Alteryx FindNearest tool to :class:`FindNearestNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["FindNearest"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        target_field = safe_get(cfg, "TargetSpatialField", "SpatialObj")
        universe_field = safe_get(cfg, "UniverseSpatialField", "SpatialObj")
        max_dist_str = safe_get(cfg, "MaxDistance", "")
        try:
            max_distance = float(max_dist_str) if max_dist_str else None
        except ValueError:
            max_distance = None
        max_matches = int(safe_get(cfg, "MaxMatches", "1") or "1")
        units = safe_get(cfg, "DistanceUnits", "Miles").lower()

        return FindNearestNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            target_field=target_field,
            universe_field=universe_field,
            max_distance=max_distance,
            max_matches=max_matches,
            distance_units=units,
            conversion_confidence=0.5,
            conversion_method="mapping",
            conversion_notes=[
                "Uses cross join + Haversine distance + Window row_number ranking.",
                "Performance may differ for large datasets; consider H3 indexing.",
            ],
        )
