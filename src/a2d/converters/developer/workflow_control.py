"""Converter for Alteryx WorkflowControl tools -> WorkflowControlNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import IRNode, WorkflowControlNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class WorkflowControlConverter(ToolConverter):
    """Converts Alteryx workflow control tools to :class:`WorkflowControlNode`.

    Supports BlockUntilDone, ControlParam, and Action tools which orchestrate
    workflow execution. In Databricks, these become notebook orchestration patterns.
    """

    @property
    def supported_tool_types(self) -> list[str]:
        return ["BlockUntilDone", "ControlParam", "Action"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        # Map tool type to control type
        control_type_map = {
            "BlockUntilDone": "block_until_done",
            "ControlParam": "control_param",
            "Action": "action",
        }
        control_type = control_type_map.get(parsed_node.tool_type, parsed_node.tool_type.lower())

        parameter_name = safe_get(cfg, "ParameterName", safe_get(cfg, "Name", ""))
        parameter_value = safe_get(cfg, "ParameterValue", safe_get(cfg, "Value", ""))

        return WorkflowControlNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            control_type=control_type,
            parameter_name=parameter_name,
            parameter_value=parameter_value,
            conversion_notes=[
                f"{parsed_node.tool_type}: workflow control requires manual orchestration in Databricks."
            ],
        )
