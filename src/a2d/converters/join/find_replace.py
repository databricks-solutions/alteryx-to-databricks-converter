"""Converter for Alteryx FindReplace tool -> FindReplaceNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import FindReplaceNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class FindReplaceConverter(ToolConverter):
    """Converts Alteryx FindReplace to :class:`FindReplaceNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["FindReplace"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        find_field = safe_get(cfg, "FindField")
        replace_field = safe_get(cfg, "ReplaceField")

        # FindMode: "Find Any Match", "Find Entire Field", "Find Begins With"
        raw_mode = safe_get(cfg, "FindMode", default="Find Entire Field")
        mode_map = {
            "Find Entire Field": "exact",
            "Find Any Match": "contains",
            "Find Begins With": "starts_with",
            "Regular Expression": "regex",
        }
        find_mode = mode_map.get(raw_mode, "exact")

        case_sensitive = safe_get(cfg, "CaseSensitive", default="True").lower() != "false"

        return FindReplaceNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            find_field=find_field,
            replace_field=replace_field,
            find_mode=find_mode,
            case_sensitive=case_sensitive,
            conversion_notes=["FindReplace maps to a PySpark join + replace pattern."],
        )
