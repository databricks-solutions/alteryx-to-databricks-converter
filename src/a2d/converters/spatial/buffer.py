"""Converter for Alteryx Buffer tool -> BufferNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import BufferNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class BufferConverter(ToolConverter):
    """Converts Alteryx Buffer tool to :class:`BufferNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Buffer"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        distance_val = float(safe_get(cfg, "DistanceValue", "1") or "1")
        units = safe_get(cfg, "DistanceUnits", "Miles").lower()
        style = safe_get(cfg, "BufferStyle", "Circle").lower()
        input_field = safe_get(cfg, "InputField", "SpatialObj")

        return BufferNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            input_field=input_field,
            buffer_distance=distance_val,
            buffer_units=units,
            buffer_style=style,
            conversion_confidence=0.6,
            conversion_method="mapping",
            conversion_notes=[
                "Uses Mosaic st_buffer; install databricks-mosaic library.",
                "Buffer distance units may need manual verification.",
            ],
        )
