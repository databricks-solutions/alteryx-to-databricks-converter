"""Converter for Alteryx RunningTotal tool -> RunningTotalNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import ensure_list, safe_get
from a2d.ir.nodes import IRNode, RunningField, RunningTotalNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class RunningTotalConverter(ToolConverter):
    """Converts Alteryx RunningTotal to :class:`RunningTotalNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["RunningTotal"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        # Running fields
        running_section = cfg.get("RunningFields", {})
        if isinstance(running_section, dict):
            raw_fields = ensure_list(running_section.get("RunningField", running_section.get("Field", [])))
        else:
            raw_fields = []

        running_fields: list[RunningField] = []
        for f in raw_fields:
            if isinstance(f, dict):
                name = safe_get(f, "@field") or safe_get(f, "@name")
                running_type = safe_get(f, "@type", default="Sum")
                if not running_type:
                    running_type = "Sum"
                output_name = safe_get(f, "@rename") or None
                running_fields.append(
                    RunningField(
                        field_name=name,
                        running_type=running_type,
                        output_field_name=output_name,
                    )
                )

        # Group by fields
        group_section = cfg.get("GroupFields", cfg.get("GroupByFields", {}))
        group_fields: list[str] = []
        if isinstance(group_section, dict):
            raw = ensure_list(group_section.get("Field", []))
            for f in raw:
                if isinstance(f, dict):
                    group_fields.append(f.get("@field", f.get("@name", "")))
                elif isinstance(f, str) and f:
                    group_fields.append(f)

        return RunningTotalNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            running_fields=running_fields,
            group_fields=group_fields,
            conversion_notes=["RunningTotal maps to PySpark window functions."],
        )
