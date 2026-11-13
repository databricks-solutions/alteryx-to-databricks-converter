"""Converter for Alteryx FindReplace tool -> FindReplaceNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import ensure_list, safe_get
from a2d.ir.nodes import FindReplaceNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class FindReplaceConverter(ToolConverter):
    """Converts Alteryx FindReplace to :class:`FindReplaceNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["FindReplace"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        # Alteryx saves the tool as:
        #   <FieldFind>     the F input's field to search in ("Find Within Field")
        #   <FieldSearch>   the R input's field holding the values to find ("Find Value")
        #   <ReplaceFoundField>  the R input's field to replace with
        #   <FindMode>      FindWhole (entire field) or FindAny (any part of it)
        #   <NoCase value=> / <MatchWholeWord value=>
        #   <ReplaceMode>   Replace, or Append (add <ReplaceAppendFields> from R)
        #   <ReplaceMultipleFound value=>  any part only: replace every found item
        cfg = parsed_node.configuration

        def flag(key: str) -> bool:
            return safe_get(cfg, key, default="False").strip().lower() == "true"

        raw_mode = safe_get(cfg, "FindMode", default="FindWhole")
        find_mode = {"FindWhole": "exact", "FindAny": "contains"}.get(raw_mode, raw_mode)
        append_block = cfg.get("ReplaceAppendFields") or {}
        append_fields = [
            f.get("@field", "")
            for f in ensure_list(append_block.get("Field", []) if isinstance(append_block, dict) else [])
            if isinstance(f, dict) and f.get("@field")
        ]
        replace_mode = "append" if safe_get(cfg, "ReplaceMode", default="Replace").lower() == "append" else "replace"

        return FindReplaceNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            find_field=safe_get(cfg, "FieldFind"),
            search_field=safe_get(cfg, "FieldSearch"),
            replace_field=safe_get(cfg, "ReplaceFoundField"),
            find_mode=find_mode,
            raw_find_mode=raw_mode,
            case_sensitive=not flag("NoCase"),
            whole_word=flag("MatchWholeWord"),
            replace_mode=replace_mode,
            replace_multiple=flag("ReplaceMultipleFound"),
            append_fields=append_fields,
            conversion_notes=["FindReplace maps to a lookup join (entire field) or a match expression (any part)."],
        )
