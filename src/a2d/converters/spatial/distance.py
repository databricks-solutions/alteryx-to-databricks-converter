"""Converter for Alteryx Distance tool -> DistanceNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import DistanceNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class DistanceConverter(ToolConverter):
    """Converts Alteryx Distance tool to :class:`DistanceNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Distance"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        source_field = safe_get(cfg, "SourceSpatialField", "SpatialObj")
        target_field = safe_get(cfg, "TargetSpatialField", "SpatialObj")
        output_field = safe_get(cfg, "OutputField", "Distance")
        units = safe_get(cfg, "DistanceUnits", "Miles").lower()

        return DistanceNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            source_field=source_field,
            target_field=target_field,
            output_field=output_field,
            distance_units=units,
            conversion_confidence=0.7,
            conversion_method="mapping",
            conversion_notes=[
                "Uses Haversine formula UDF or Mosaic st_distance.",
                "Distance units are converted; verify precision requirements.",
            ],
        )
