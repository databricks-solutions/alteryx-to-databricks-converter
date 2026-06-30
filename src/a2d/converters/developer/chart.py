"""Converter for Alteryx chart tools -> ChartNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import ChartNode, IRNode
from a2d.parser.schema import ParsedNode


def _parse_series_fields(cfg: dict) -> list[str]:
    """Extract series fields from config, handling various formats."""
    series_fields = []

    # Try SeriesFields as list
    series = cfg.get("SeriesFields", [])
    if isinstance(series, list):
        series_fields = [str(s) for s in series if s]
    elif isinstance(series, str) and series:
        series_fields = [series]

    # Also check for Series field
    if not series_fields:
        series = cfg.get("Series", "")
        if series:
            series_fields = [str(series)]

    return series_fields


@ConverterRegistry.register
class ChartConverter(ToolConverter):
    """Converts Alteryx Chart and InteractiveChart tools to :class:`ChartNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Chart", "InteractiveChart"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        # Extract chart configuration
        chart_type = safe_get(cfg, "ChartType", "bar").lower()
        x_field = safe_get(cfg, "XField", safe_get(cfg, "XAxis", ""))
        y_field = safe_get(cfg, "YField", safe_get(cfg, "YAxis", ""))
        series_fields = _parse_series_fields(cfg)
        title = safe_get(cfg, "Title", safe_get(cfg, "ChartTitle", ""))

        return ChartNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            chart_type=chart_type,
            x_field=x_field,
            y_field=y_field,
            series_fields=series_fields,
            title=title,
            conversion_notes=["Chart visualization; consider using Databricks display() or plotly."],
        )
