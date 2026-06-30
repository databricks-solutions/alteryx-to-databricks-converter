"""Converter for Alteryx MakeGrid tool -> MakeGridNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import IRNode, MakeGridNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class MakeGridConverter(ToolConverter):
    """Converts Alteryx MakeGrid tool to :class:`MakeGridNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["MakeGrid"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        grid_size = float(safe_get(cfg, "GridSize", "1") or "1")
        units = safe_get(cfg, "GridUnits", "Miles").lower()
        extent_field = safe_get(cfg, "ExtentField", "SpatialObj")

        return MakeGridNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            extent_field=extent_field,
            grid_size=grid_size,
            grid_units=units,
            conversion_confidence=0.5,
            conversion_method="mapping",
            conversion_notes=[
                "Uses H3 polyfill or Mosaic grid_tessellate for grid creation.",
                "Grid cell size mapping may need calibration.",
            ],
        )
