"""Converter for Alteryx AppendFields tool -> AppendFieldsNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import ensure_list
from a2d.ir.nodes import AppendFieldsNode, FieldAction, FieldOperation, IRNode
from a2d.parser.schema import ParsedNode


def _parse_field_ops(cfg: dict, section_key: str) -> list[FieldOperation]:
    section = cfg.get(section_key, {})
    if not isinstance(section, dict):
        return []
    raw = ensure_list(section.get("SelectField", section.get("Field", [])))
    ops: list[FieldOperation] = []
    for f in raw:
        if isinstance(f, dict):
            name = f.get("@field", f.get("@name", ""))
            selected = f.get("@selected", "True").lower() != "false"
            action = FieldAction.SELECT if selected else FieldAction.DESELECT
            ops.append(FieldOperation(field_name=name, action=action, selected=selected))
    return ops


@ConverterRegistry.register
class AppendFieldsConverter(ToolConverter):
    """Converts Alteryx AppendFields to :class:`AppendFieldsNode`.

    AppendFields performs a cross-join, appending every row from the source
    to every row of the target.
    """

    @property
    def supported_tool_types(self) -> list[str]:
        return ["AppendFields"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        allow_all = cfg.get("AllowAllAppends", "True")
        allow_all_appends = allow_all.lower() != "false" if isinstance(allow_all, str) else True

        select_target = _parse_field_ops(cfg, "SelectTargetFields")
        select_source = _parse_field_ops(cfg, "SelectSourceFields")

        return AppendFieldsNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            allow_all_appends=allow_all_appends,
            select_target=select_target,
            select_source=select_source,
            conversion_notes=["AppendFields is a cross-join; can produce very large result sets."],
        )
