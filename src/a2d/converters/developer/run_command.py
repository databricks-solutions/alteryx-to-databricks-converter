"""Converter for Alteryx RunCommand tool -> RunCommandNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import IRNode, RunCommandNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class RunCommandConverter(ToolConverter):
    """Converts Alteryx RunCommand to :class:`RunCommandNode`.

    RunCommand executes shell commands, which is generally discouraged
    in Databricks.  This converter stubs out the node and flags it for
    manual review.
    """

    @property
    def supported_tool_types(self) -> list[str]:
        return ["RunCommand"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        command = safe_get(cfg, "Command")
        command_arguments = safe_get(cfg, "Arguments") or safe_get(cfg, "CmdArgs")
        working_directory = safe_get(cfg, "WorkingDirectory") or safe_get(cfg, "Directory")
        write_source = safe_get(cfg, "WriteSource") or safe_get(cfg, "PreCommand")
        read_results = safe_get(cfg, "ReadResults") or safe_get(cfg, "PostCommand")

        return RunCommandNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            command=command,
            command_arguments=command_arguments,
            working_directory=working_directory,
            write_source=write_source,
            read_results=read_results,
            conversion_confidence=0.2,
            conversion_notes=[
                "RunCommand requires manual conversion.",
                "Shell commands cannot run directly on Databricks clusters; "
                "consider %sh magic or Databricks CLI tasks.",
            ],
        )
