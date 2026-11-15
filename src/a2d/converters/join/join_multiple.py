"""Converter for Alteryx JoinMultiple tool -> JoinMultipleNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import ensure_list, safe_get
from a2d.ir.nodes import IRNode, JoinKey, JoinMultipleNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class JoinMultipleConverter(ToolConverter):
    """Converts Alteryx JoinMultiple to :class:`JoinMultipleNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["JoinMultiple"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        # What Designer saves: JoinByRecPos, one JoinInfo per input ("#1", "#2", ...)
        # with its key fields in order, OutputJoinOnly, and a select list.
        by_position = _flag(cfg.get("JoinByRecPos"))
        keys_by_input: dict[int, list[str]] = {}
        join_fields = cfg.get("JoinFields")
        for info in ensure_list(join_fields.get("JoinInfo") if isinstance(join_fields, dict) else None):
            if not isinstance(info, dict):
                continue
            number = str(info.get("@connection", "")).lstrip("#")
            if number.isdigit():
                fields = [f.get("@field", "") for f in ensure_list(info.get("Field")) if isinstance(f, dict)]
                keys_by_input[int(number)] = [f for f in fields if f]

        # An older two-sided form (left/right pairs) some files and tests use.
        join_info = cfg.get("JoinInfo", {})
        raw_keys = (
            ensure_list(join_info.get("Field", join_info.get("JoinField", []))) if isinstance(join_info, dict) else []
        )
        keys: list[JoinKey] = []
        for k in raw_keys:
            if isinstance(k, dict):
                left = k.get("@left", k.get("@LeftField", ""))
                right = k.get("@right", k.get("@RightField", ""))
                if left and right:
                    keys.append(JoinKey(left_field=left, right_field=right))

        if "OutputJoinOnly" in cfg:
            join_type = "inner" if _flag(cfg.get("OutputJoinOnly")) else "full"
        else:
            join_type = safe_get(cfg, "JoinType", default="inner").lower()
            if join_type not in ("inner", "left", "right", "full"):
                join_type = "inner"

        select_fields: list[tuple[str, bool, str | None]] = []
        keep_unlisted = True
        select_cfg = cfg.get("SelectConfiguration")
        inner = select_cfg.get("Configuration") if isinstance(select_cfg, dict) else None
        select = inner.get("SelectFields") if isinstance(inner, dict) else None
        for item in ensure_list(select.get("SelectField") if isinstance(select, dict) else None):
            if not isinstance(item, dict) or not item.get("@field"):
                continue
            selected = str(item.get("@selected", "True")).lower() == "true"
            if item["@field"] == "*Unknown":
                keep_unlisted = selected
                continue
            select_fields.append((item["@field"], selected, item.get("@rename") or None))

        input_count_str = safe_get(cfg, "InputCount", default="")
        input_count = int(input_count_str) if input_count_str.isdigit() else max(2, len(keys_by_input))

        notes = ["JoinMultiple maps to chained PySpark joins."]
        if not by_position and keys_by_input and len({len(v) for v in keys_by_input.values()}) > 1:
            notes.append("The inputs don't all have the same number of key fields.")
        return JoinMultipleNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            join_keys=keys,
            join_type=join_type,
            input_count=input_count,
            by_position=by_position,
            keys_by_input=keys_by_input,
            select_fields=select_fields,
            keep_unlisted=keep_unlisted,
            conversion_notes=notes,
        )


def _flag(value: object) -> bool:
    if isinstance(value, dict):
        value = value.get("@value", value.get("#text", ""))
    return str(value).strip().lower() == "true"
