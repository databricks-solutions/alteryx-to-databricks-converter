"""Converter for Alteryx Unique tool -> UniqueNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import ensure_list
from a2d.ir.nodes import IRNode, UniqueNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class UniqueConverter(ToolConverter):
    """Converts Alteryx Unique to :class:`UniqueNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Unique"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        # UniqueFields -> Field (list of dicts or single dict)
        unique_fields_section = cfg.get("UniqueFields", {})
        if isinstance(unique_fields_section, dict):
            raw_fields = ensure_list(unique_fields_section.get("Field", []))
        else:
            raw_fields = []

        key_fields: list[str] = []
        for f in raw_fields:
            if isinstance(f, dict):
                name = f.get("@field", f.get("@name", ""))
                if name:
                    key_fields.append(name)
            elif isinstance(f, str) and f:
                key_fields.append(f)

        return UniqueNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            key_fields=key_fields,
        )
