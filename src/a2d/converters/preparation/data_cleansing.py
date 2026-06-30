"""Converter for Alteryx DataCleansing tool -> DataCleansingNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import ensure_list, safe_get
from a2d.ir.nodes import DataCleansingNode, IRNode
from a2d.parser.schema import ParsedNode


def _bool_get(d: object, key: str, default: bool = False) -> bool:
    val = safe_get(d, key)
    if val.lower() in ("true", "1", "yes"):
        return True
    if val.lower() in ("false", "0", "no"):
        return False
    return default


@ConverterRegistry.register
class DataCleansingConverter(ToolConverter):
    """Converts Alteryx DataCleansing to :class:`DataCleansingNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["DataCleansing"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        # Fields to cleanse
        fields_section = cfg.get("Fields", {})
        fields: list[str] = []
        if isinstance(fields_section, dict):
            raw = ensure_list(fields_section.get("Field", []))
            for f in raw:
                if isinstance(f, dict):
                    fields.append(f.get("@field", f.get("@name", "")))
                elif isinstance(f, str) and f:
                    fields.append(f)

        # Cleansing options
        remove_null = _bool_get(cfg, "ReplaceNulls") or _bool_get(cfg, "RemoveNull")
        trim_whitespace = _bool_get(cfg, "TrimWhitespace")
        remove_tabs = _bool_get(cfg, "RemoveTabs")
        remove_line_breaks = _bool_get(cfg, "RemoveLineBreaks")
        remove_duplicate_whitespace = _bool_get(cfg, "RemoveDuplicateWhitespace")

        replace_nulls_with = safe_get(cfg, "ReplaceNullsWith") or None
        modify_case = safe_get(cfg, "ModifyCase") or None
        if modify_case:
            modify_case = modify_case.lower()

        return DataCleansingNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            fields=fields,
            remove_null=remove_null,
            trim_whitespace=trim_whitespace,
            remove_tabs=remove_tabs,
            remove_line_breaks=remove_line_breaks,
            remove_duplicate_whitespace=remove_duplicate_whitespace,
            replace_nulls_with=replace_nulls_with,
            modify_case=modify_case,
        )
