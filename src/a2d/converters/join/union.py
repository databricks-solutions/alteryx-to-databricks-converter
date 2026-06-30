"""Converter for Alteryx Union (UnionV2) tool -> UnionNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import IRNode, UnionNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class UnionConverter(ToolConverter):
    """Converts Alteryx Union (UnionV2) to :class:`UnionNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Union"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        # Mode: "Auto Config by Name", "Auto Config by Position", "Manually Configure"
        raw_mode = safe_get(cfg, "Mode", default="Auto Config by Name")
        mode_map = {
            "Auto Config by Name": "name",
            "Auto Config by Position": "position",
            "Manually Configure": "manual",
        }
        mode = mode_map.get(raw_mode, "auto")

        allow_missing = safe_get(cfg, "SetAllOutputFields", default="True").lower() != "false"

        return UnionNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            mode=mode,
            allow_missing=allow_missing,
        )
