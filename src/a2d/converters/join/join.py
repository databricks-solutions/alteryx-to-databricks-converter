"""Converter for Alteryx Join tool -> JoinNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import ensure_list
from a2d.ir.nodes import (
    FieldAction,
    FieldOperation,
    IRNode,
    JoinKey,
    JoinNode,
)
from a2d.parser.schema import ParsedNode


def _parse_join_keys(cfg: dict) -> list[JoinKey]:
    """Extract join key pairs from the configuration."""
    join_info = cfg.get("JoinInfo", cfg.get("JoinFields", {}))
    if isinstance(join_info, dict):
        raw_keys = ensure_list(join_info.get("Field", join_info.get("JoinField", [])))
    elif isinstance(join_info, list):
        # Old XML format: two <JoinInfo connection="Left/Right"> elements,
        # each with a @field attribute.  Pair them positionally.
        left_fields: list[str] = []
        right_fields: list[str] = []
        for entry in join_info:
            if not isinstance(entry, dict):
                continue
            conn = entry.get("@connection", "")
            # Field is a child element: <Field field="X"/> → {"Field": {"@field": "X"}}
            # Fall back to @field directly on entry for older XML shapes.
            field_elem = entry.get("Field", {})
            if isinstance(field_elem, dict):
                field_name = field_elem.get("@field", entry.get("@field", ""))
            else:
                field_name = entry.get("@field", "")
            if conn == "Left":
                left_fields.append(field_name)
            elif conn == "Right":
                right_fields.append(field_name)
        keys: list[JoinKey] = []
        for lf, rf in zip(left_fields, right_fields, strict=False):
            if lf and rf:
                keys.append(JoinKey(left_field=lf, right_field=rf))
        return keys
    else:
        raw_keys = []

    keys = []
    for k in raw_keys:
        if isinstance(k, dict):
            left = k.get("@left", k.get("@LeftField", ""))
            right = k.get("@right", k.get("@RightField", ""))
            if left and right:
                keys.append(JoinKey(left_field=left, right_field=right))
    return keys


def _parse_field_ops(cfg: dict, section_key: str) -> list[FieldOperation]:
    """Parse field selection operations for one side of a join (legacy key format)."""
    section = cfg.get(section_key, {})
    if not isinstance(section, dict):
        return []
    raw = ensure_list(section.get("SelectField", section.get("Field", [])))
    ops: list[FieldOperation] = []
    for f in raw:
        if isinstance(f, dict):
            name = f.get("@field", f.get("@name", ""))
            selected = f.get("@selected", "True").lower() != "false"
            rename_to = f.get("@rename", None) or None
            action = FieldAction.RENAME if rename_to else (FieldAction.SELECT if selected else FieldAction.DESELECT)
            ops.append(
                FieldOperation(
                    field_name=name,
                    action=action,
                    rename_to=rename_to,
                    selected=selected,
                )
            )
    return ops


def _parse_select_configuration(cfg: dict) -> tuple[list[FieldOperation], list[FieldOperation]]:
    """Parse SelectConfiguration XML block into (left_ops, right_ops).

    Alteryx Join stores field selection/rename under::

        <SelectConfiguration>
          <Configuration outputConnection="Join">
            <SelectFields>
              <SelectField field="X" selected="True" rename="" input="Left_"/>
              ...
            </SelectFields>
          </Configuration>
        </SelectConfiguration>

    The ``@input`` attribute is ``"Left_"`` or ``"Right_"`` (with trailing
    underscore) to indicate which side the field belongs to.
    """
    select_cfg = cfg.get("SelectConfiguration", {})
    if not isinstance(select_cfg, dict):
        return [], []

    # Configuration may be a single dict or a list (one per outputConnection)
    raw_configs = ensure_list(select_cfg.get("Configuration", {}))

    # Prefer the "Join" outputConnection; fall back to the first entry
    config_dict: dict = {}
    for c in raw_configs:
        if isinstance(c, dict) and c.get("@outputConnection", "").lower() == "join":
            config_dict = c
            break
    if not config_dict and raw_configs:
        config_dict = raw_configs[0] if isinstance(raw_configs[0], dict) else {}

    select_fields_block = config_dict.get("SelectFields", {})
    if not isinstance(select_fields_block, dict):
        return [], []

    raw_fields = ensure_list(select_fields_block.get("SelectField", []))

    left_ops: list[FieldOperation] = []
    right_ops: list[FieldOperation] = []

    for f in raw_fields:
        if not isinstance(f, dict):
            continue
        name = f.get("@field", "")
        selected = f.get("@selected", "True").lower() != "false"
        rename_to = f.get("@rename", None) or None
        input_side = f.get("@input", "")  # "Left_" or "Right_"
        action = FieldAction.RENAME if rename_to else (FieldAction.SELECT if selected else FieldAction.DESELECT)
        op = FieldOperation(
            field_name=name,
            action=action,
            rename_to=rename_to,
            selected=selected,
        )
        if input_side.startswith("Left"):
            left_ops.append(op)
        elif input_side.startswith("Right"):
            right_ops.append(op)

    return left_ops, right_ops


@ConverterRegistry.register
class JoinConverter(ToolConverter):
    """Converts Alteryx Join to :class:`JoinNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Join"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        join_keys = _parse_join_keys(cfg)

        # Alteryx Join always does an inner join; the unmatched rows go to
        # separate output anchors (Left=L, Right=R, Join=J).
        # We map it as "inner" by default.
        join_type = "inner"

        # Try the new SelectConfiguration XML format first; fall back to legacy keys.
        select_left, select_right = _parse_select_configuration(cfg)
        if not select_left and not select_right:
            select_left = _parse_field_ops(cfg, "SelectLeftFields")
            select_right = _parse_field_ops(cfg, "SelectRightFields")

        return JoinNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            join_keys=join_keys,
            join_type=join_type,
            select_left=select_left,
            select_right=select_right,
            conversion_notes=[
                "Alteryx Join produces 3 outputs (J/L/R); downstream connections determine effective join type."
            ],
        )
