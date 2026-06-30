"""Converter for Alteryx DynamicRename tool -> DynamicRenameNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import DynamicRenameNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class DynamicRenameConverter(ToolConverter):
    """Converts Alteryx DynamicRename to :class:`DynamicRenameNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["DynamicRename"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        rename_mode = safe_get(cfg, "RenameMode", "FirstRow")

        return DynamicRenameNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            rename_mode=rename_mode,
            conversion_notes=[
                f"DynamicRename in {rename_mode} mode; manual review recommended to verify column mapping."
            ],
        )
