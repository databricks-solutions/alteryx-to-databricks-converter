"""Converter for Alteryx TextToColumns tool -> TextToColumnsNode."""

from __future__ import annotations

import html

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import IRNode, TextToColumnsNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class TextToColumnsConverter(ToolConverter):
    """Converts Alteryx TextToColumns to :class:`TextToColumnsNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["TextToColumns"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        field_name = safe_get(cfg, "Field")
        delimiter = html.unescape(safe_get(cfg, "Delimiter", default=","))
        if delimiter == "\\t":
            delimiter = "\t"
        if delimiter == "\\n":
            delimiter = "\n"

        # Split to columns or rows
        split_to = safe_get(cfg, "SplitTo", default="Columns").lower()
        if split_to not in ("columns", "rows"):
            split_to = "columns"

        num_cols_str = safe_get(cfg, "NumFields") or safe_get(cfg, "NumColumns")
        num_columns = int(num_cols_str) if num_cols_str and num_cols_str.isdigit() else None

        output_root_name = safe_get(cfg, "RootName") or safe_get(cfg, "OutputRootName")
        skip_empty = safe_get(cfg, "SkipEmpty", default="False").lower() == "true"

        return TextToColumnsNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            field_name=field_name,
            delimiter=delimiter,
            split_to=split_to,
            num_columns=num_columns,
            output_root_name=output_root_name,
            skip_empty=skip_empty,
        )
