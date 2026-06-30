"""Converter for Alteryx SpatialMatch tool -> SpatialMatchNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import IRNode, SpatialMatchNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class SpatialMatchConverter(ToolConverter):
    """Converts Alteryx SpatialMatch tool to :class:`SpatialMatchNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["SpatialMatch"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        match_type = safe_get(cfg, "MatchType", "Intersects").lower()
        target_field = safe_get(cfg, "TargetSpatialField", "SpatialObj")
        universe_field = safe_get(cfg, "UniverseSpatialField", "SpatialObj")

        return SpatialMatchNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            spatial_field_target=target_field,
            spatial_field_universe=universe_field,
            match_type=match_type,
            conversion_confidence=0.5,
            conversion_method="mapping",
            conversion_notes=[
                "Uses Mosaic st_intersects/st_contains; install databricks-mosaic library.",
                "Spatial relationship semantics may differ slightly from Alteryx.",
            ],
        )
