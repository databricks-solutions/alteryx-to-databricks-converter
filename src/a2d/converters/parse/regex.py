"""Converter for Alteryx RegEx tool -> RegExNode."""

from __future__ import annotations

import html

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import ensure_list, safe_get
from a2d.ir.nodes import IRNode, RegExNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class RegExConverter(ToolConverter):
    """Converts Alteryx RegEx to :class:`RegExNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["RegEx"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        field_name = safe_get(cfg, "Field")
        expression = html.unescape(safe_get(cfg, "RegExExpression") or safe_get(cfg, "Expression"))
        replacement = html.unescape(safe_get(cfg, "Replacement") or safe_get(cfg, "ReplaceExpression"))

        # Mode: "ParseSimple", "Match", "Replace", "Tokenize", "ParseColumns"
        raw_mode = safe_get(cfg, "Mode") or safe_get(cfg, "RegExMode")
        mode_map = {
            "ParseSimple": "parse",
            "ParseColumns": "parse",
            "Match": "match",
            "Replace": "replace",
            "Tokenize": "tokenize",
        }
        mode = mode_map.get(raw_mode, raw_mode.lower() if raw_mode else "parse")

        case_insensitive = safe_get(cfg, "CaseInsensitive", default="False").lower() == "true"

        # Output fields (for parse mode)
        output_fields: list[str] = []
        output_section = cfg.get("OutputFields", cfg.get("Fields", {}))
        if isinstance(output_section, dict):
            raw = ensure_list(output_section.get("Field", []))
            for f in raw:
                if isinstance(f, dict):
                    output_fields.append(f.get("@field", f.get("@name", "")))
                elif isinstance(f, str) and f:
                    output_fields.append(f)

        return RegExNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            field_name=field_name,
            expression=expression,
            mode=mode,
            output_fields=output_fields,
            case_insensitive=case_insensitive,
            replacement=replacement,
        )
