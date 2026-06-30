"""Converter for Alteryx report tools -> ReportNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import IRNode, ReportNode
from a2d.parser.schema import ParsedNode


def _parse_fields(cfg: dict) -> list[str]:
    """Extract fields from config, handling various formats."""
    fields = []

    # Try Fields as list
    field_list = cfg.get("Fields", [])
    if isinstance(field_list, list):
        fields = [str(f) for f in field_list if f]
    elif isinstance(field_list, str) and field_list:
        fields = [field_list]

    # Also check for Columns field
    if not fields:
        columns = cfg.get("Columns", [])
        if isinstance(columns, list):
            fields = [str(c) for c in columns if c]
        elif isinstance(columns, str) and columns:
            fields = [columns]

    return fields


@ConverterRegistry.register
class ReportConverter(ToolConverter):
    """Converts Alteryx report tools (Table, Layout, Render) to :class:`ReportNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Table", "Layout", "Render"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        # Report type is based on tool type
        report_type = parsed_node.tool_type.lower()

        # Extract report configuration
        title = safe_get(cfg, "Title", safe_get(cfg, "ReportTitle", ""))
        fields = _parse_fields(cfg)
        output_format = safe_get(cfg, "OutputFormat", safe_get(cfg, "Format", "")).lower()

        # Default format based on tool type
        if not output_format:
            if report_type == "render":
                output_format = "pdf"
            elif report_type == "table":
                output_format = "html"
            else:
                output_format = ""

        return ReportNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            report_type=report_type,
            title=title,
            fields=fields,
            output_format=output_format,
            conversion_notes=[f"Report {report_type}; consider using Databricks notebooks for reporting."],
        )
