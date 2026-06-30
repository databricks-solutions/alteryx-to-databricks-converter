"""Converter for Alteryx FieldSummary tool -> FieldSummaryNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import FieldSummaryNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class FieldSummaryConverter(ToolConverter):
    """Converts Alteryx FieldSummary tool to :class:`FieldSummaryNode`.

    FieldSummary generates column-level statistics (count, distinct count, min,
    max, etc.). Maps to DataFrame describe() or profiling operations.
    """

    @property
    def supported_tool_types(self) -> list[str]:
        return ["FieldSummary"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        # Extract fields list
        fields: list[str] = []
        fields_raw = cfg.get("Fields", cfg.get("FieldList", []))

        if isinstance(fields_raw, list):
            for field_item in fields_raw:
                if isinstance(field_item, dict):
                    field_name = safe_get(field_item, "field", safe_get(field_item, "name", ""))
                elif isinstance(field_item, str):
                    field_name = field_item
                else:
                    continue

                if field_name:
                    fields.append(field_name)
        elif isinstance(fields_raw, str):
            # Single field or comma-separated
            fields = [f.strip() for f in fields_raw.split(",") if f.strip()]

        # Extract statistics types
        statistics: list[str] = []
        stats_raw = cfg.get("Statistics", cfg.get("StatTypes", []))

        if isinstance(stats_raw, list):
            for stat_item in stats_raw:
                if isinstance(stat_item, dict):
                    stat_type = safe_get(stat_item, "type", safe_get(stat_item, "name", ""))
                elif isinstance(stat_item, str):
                    stat_type = stat_item
                else:
                    continue

                if stat_type:
                    statistics.append(stat_type)
        elif isinstance(stats_raw, str):
            statistics = [s.strip() for s in stats_raw.split(",") if s.strip()]

        # Default statistics if none specified
        if not statistics:
            statistics = ["count", "distinct", "min", "max", "mean"]

        return FieldSummaryNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            fields=fields,
            statistics=statistics,
            conversion_notes=["FieldSummary: maps to DataFrame.describe() or profiling operations."],
        )
