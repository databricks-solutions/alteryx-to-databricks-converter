"""Converter for Alteryx CrossTab tool -> CrossTabNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import ensure_list, safe_get
from a2d.ir.nodes import CrossTabNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class CrossTabConverter(ToolConverter):
    """Converts Alteryx CrossTab to :class:`CrossTabNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["CrossTab"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        # Group-by fields
        group_section = cfg.get("GroupFields", {})
        group_fields: list[str] = []
        if isinstance(group_section, dict):
            raw = ensure_list(group_section.get("Field", []))
            for f in raw:
                if isinstance(f, dict):
                    group_fields.append(f.get("@field", f.get("@name", "")))
                elif isinstance(f, str) and f:
                    group_fields.append(f)

        header_field = safe_get(cfg, "HeaderField")
        value_field = safe_get(cfg, "ValueField") or safe_get(cfg, "DataField")
        aggregation = safe_get(cfg, "Aggregation", default="Sum") or safe_get(cfg, "Method", default="Sum")
        separator = safe_get(cfg, "Separator", default="_")

        return CrossTabNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            group_fields=group_fields,
            header_field=header_field,
            value_field=value_field,
            aggregation=aggregation,
            separator=separator,
        )
