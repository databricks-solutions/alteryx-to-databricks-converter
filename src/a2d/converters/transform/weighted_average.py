"""Converter for Alteryx WeightedAverage tool -> WeightedAverageNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import IRNode, WeightedAverageNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class WeightedAverageConverter(ToolConverter):
    """Converts Alteryx WeightedAverage tool to :class:`WeightedAverageNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["WeightedAverage"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        value_field = safe_get(cfg, "ValueField", safe_get(cfg, "Value", ""))
        weight_field = safe_get(cfg, "WeightField", safe_get(cfg, "Weight", ""))
        output_field = safe_get(cfg, "OutputField", "WeightedAvg")

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

        return WeightedAverageNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            value_field=value_field,
            weight_field=weight_field,
            group_fields=group_fields,
            output_field=output_field,
        )
