"""Converter for Alteryx Select (AlteryxSelect) tool -> SelectNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import ensure_list
from a2d.ir.nodes import FieldAction, FieldOperation, IRNode, SelectNode
from a2d.parser.schema import ParsedNode


def _parse_field_operation(field_cfg: dict) -> FieldOperation:
    """Parse a single <SelectField> dict into a FieldOperation."""
    name = field_cfg.get("@field", field_cfg.get("@name", ""))
    selected = field_cfg.get("@selected", "True").lower() != "false"
    rename_to = field_cfg.get("@rename") or None
    new_type = field_cfg.get("@type") or None
    new_size_str = field_cfg.get("@size")
    new_size = int(new_size_str) if new_size_str and new_size_str.isdigit() else None
    description = field_cfg.get("@description") or None

    # Determine the primary action
    if not selected:
        action = FieldAction.DESELECT
    elif rename_to:
        action = FieldAction.RENAME
    elif new_type:
        action = FieldAction.RETYPE
    elif new_size is not None:
        action = FieldAction.RESIZE
    else:
        action = FieldAction.SELECT

    return FieldOperation(
        field_name=name,
        action=action,
        rename_to=rename_to,
        new_type=new_type,
        new_size=new_size,
        selected=selected,
        description=description,
    )


@ConverterRegistry.register
class SelectConverter(ToolConverter):
    """Converts Alteryx Select to :class:`SelectNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Select"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        # SelectFields may be nested: Configuration -> SelectFields -> SelectField
        select_fields_section = cfg.get("SelectFields", cfg.get("Configuration", {}))
        if isinstance(select_fields_section, dict):
            raw_fields = ensure_list(select_fields_section.get("SelectField", []))
        else:
            raw_fields = []

        operations = []
        for f in raw_fields:
            if isinstance(f, dict):
                operations.append(_parse_field_operation(f))

        # Check for "*Unknown" wildcard field
        select_all_unknown = True
        for f in raw_fields:
            if isinstance(f, dict) and f.get("@field") == "*Unknown":
                select_all_unknown = f.get("@selected", "True").lower() != "false"
                break

        return SelectNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            field_operations=operations,
            select_all_unknown=select_all_unknown,
        )
