"""Converter for Alteryx Summarize tool -> SummarizeNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import ensure_list, safe_get
from a2d.ir.nodes import AggAction, AggregationField, IRNode, SummarizeNode
from a2d.parser.schema import ParsedNode

# Map Alteryx action strings to AggAction enum values
_ACTION_MAP: dict[str, AggAction] = {
    "GroupBy": AggAction.GROUP_BY,
    "Sum": AggAction.SUM,
    "Count": AggAction.COUNT,
    "CountDistinct": AggAction.COUNT_DISTINCT,
    "Min": AggAction.MIN,
    "Max": AggAction.MAX,
    "Avg": AggAction.AVG,
    "First": AggAction.FIRST,
    "Last": AggAction.LAST,
    "Concat": AggAction.CONCAT,
    "StdDev": AggAction.STD_DEV,
    "Variance": AggAction.VARIANCE,
    "Median": AggAction.MEDIAN,
    "Mode": AggAction.MODE,
    "Percentile": AggAction.PERCENTILE,
    "CountNonNull": AggAction.COUNT_NON_NULL,
    "CountNull": AggAction.COUNT_NULL,
    "SpatialObjCombine": AggAction.SPATIAL_COMBINE,
}


@ConverterRegistry.register
class SummarizeConverter(ToolConverter):
    """Converts Alteryx Summarize to :class:`SummarizeNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Summarize"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        # SummarizeFields -> SummarizeField (list of dicts)
        summary_section = cfg.get("SummarizeFields", {})
        if isinstance(summary_section, dict):
            raw_fields = ensure_list(summary_section.get("SummarizeField", []))
        else:
            raw_fields = ensure_list(summary_section)

        aggregations: list[AggregationField] = []
        for f in raw_fields:
            if isinstance(f, dict):
                field_name = safe_get(f, "@field") or safe_get(f, "@name")
                action_str = safe_get(f, "@action") or safe_get(f, "@type")
                output_name = safe_get(f, "@rename") or None
                separator = safe_get(f, "@separator", default=",")
                pct_str = safe_get(f, "@percentile")
                pct_val = float(pct_str) if pct_str else None

                action = _ACTION_MAP.get(action_str, AggAction.GROUP_BY)

                aggregations.append(
                    AggregationField(
                        field_name=field_name,
                        action=action,
                        output_field_name=output_name,
                        separator=separator,
                        percentile_value=pct_val,
                    )
                )

        return SummarizeNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            aggregations=aggregations,
        )
