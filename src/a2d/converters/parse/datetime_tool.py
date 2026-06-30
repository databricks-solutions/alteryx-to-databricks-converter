"""Converter for Alteryx DateTime tool -> DateTimeNode."""

from __future__ import annotations

import html

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import DateTimeNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class DateTimeConverter(ToolConverter):
    """Converts Alteryx DateTime to :class:`DateTimeNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["DateTime"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        input_field = safe_get(cfg, "InputField") or safe_get(cfg, "InField")
        output_field = safe_get(cfg, "OutputField") or safe_get(cfg, "OutField")

        # Conversion mode: DateTimeParse, DateTimeFormat, DateTimeAdd, etc.
        conversion_mode = safe_get(cfg, "ConversionMode") or safe_get(cfg, "Mode")
        mode_map = {
            "DateTimeParse": "parse",
            "DateTimeFormat": "format",
            "DateTimeAdd": "date_add",
            "DateTimeDiff": "date_diff",
            "DateTimeNow": "now",
        }
        conversion_mode = mode_map.get(conversion_mode, conversion_mode.lower() if conversion_mode else "")

        format_string = html.unescape(safe_get(cfg, "FormatString") or safe_get(cfg, "Format"))
        language = safe_get(cfg, "Language", default="English")

        return DateTimeNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            input_field=input_field,
            output_field=output_field,
            conversion_mode=conversion_mode,
            format_string=format_string,
            language=language,
        )
