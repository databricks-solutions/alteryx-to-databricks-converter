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

        # Join keys
        join_info = cfg.get("JoinInfo", cfg.get("JoinFields", {}))
        if isinstance(join_info, dict):
            raw_keys = ensure_list(join_info.get("Field", join_info.get("JoinField", [])))
        else:
            raw_keys = []

        keys: list[JoinKey] = []
        for k in raw_keys:
            if isinstance(k, dict):
                left = k.get("@left", k.get("@LeftField", ""))
                right = k.get("@right", k.get("@RightField", ""))
                if left and right:
                    keys.append(JoinKey(left_field=left, right_field=right))

        join_type = safe_get(cfg, "JoinType", default="inner").lower()
        if join_type not in ("inner", "left", "right", "full"):
            join_type = "inner"

        input_count_str = safe_get(cfg, "InputCount", default="2")
        input_count = int(input_count_str) if input_count_str.isdigit() else 2

        return JoinMultipleNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            join_keys=keys,
            join_type=join_type,
            input_count=input_count,
            conversion_notes=["JoinMultiple maps to chained PySpark joins."],
        )
