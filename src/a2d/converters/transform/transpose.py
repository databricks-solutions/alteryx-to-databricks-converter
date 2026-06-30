"""Converter for Alteryx Transpose tool -> TransposeNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import ensure_list, safe_get
from a2d.ir.nodes import IRNode, TransposeNode
from a2d.parser.schema import ParsedNode


def _extract_field_list(cfg: dict, section_key: str) -> list[str]:
    """Extract a list of field names from a config section."""
    section = cfg.get(section_key, {})
    fields: list[str] = []
    if isinstance(section, dict):
        raw = ensure_list(section.get("Field", []))
        for f in raw:
            if isinstance(f, dict):
                fields.append(f.get("@field", f.get("@name", "")))
            elif isinstance(f, str) and f:
                fields.append(f)
    return fields


@ConverterRegistry.register
class TransposeConverter(ToolConverter):
    """Converts Alteryx Transpose to :class:`TransposeNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Transpose"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        key_fields = _extract_field_list(cfg, "KeyFields")
        data_fields = _extract_field_list(cfg, "DataFields")

        header_name = safe_get(cfg, "HeaderName", default="Name")
        if not header_name:
            header_name = "Name"
        value_name = safe_get(cfg, "ValueName", default="Value")
        if not value_name:
            value_name = "Value"

        enable_key = safe_get(cfg, "EnableKeyFields", default="True").lower() != "false"

        return TransposeNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            key_fields=key_fields,
            data_fields=data_fields,
            header_name=header_name,
            value_name=value_name,
            enable_key_fields=enable_key,
        )
