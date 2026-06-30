"""Converter for Alteryx Arrange tool -> SelectNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import FieldAction, FieldOperation, IRNode, SelectNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class ArrangeConverter(ToolConverter):
    """Converts Alteryx Arrange tool to :class:`SelectNode`.

    Arrange reorders columns in the dataset. This maps to SelectNode with
    REORDER field operations.
    """

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Arrange"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        field_operations: list[FieldOperation] = []

        # Parse field ordering from configuration
        # Common keys: "Fields", "FieldOrder", "OrderedFields"
        fields_raw = cfg.get("Fields", cfg.get("FieldOrder", cfg.get("OrderedFields", [])))

        if isinstance(fields_raw, list):
            for field_item in fields_raw:
                if isinstance(field_item, dict):
                    field_name = safe_get(field_item, "field", safe_get(field_item, "name", ""))
                elif isinstance(field_item, str):
                    field_name = field_item
                else:
                    continue

                if field_name:
                    field_operations.append(
                        FieldOperation(
                            field_name=field_name,
                            action=FieldAction.REORDER,
                            selected=True,
                        )
                    )
        elif isinstance(fields_raw, str):
            # Single field or comma-separated
            for field_name in fields_raw.split(","):
                field_name = field_name.strip()
                if field_name:
                    field_operations.append(
                        FieldOperation(
                            field_name=field_name,
                            action=FieldAction.REORDER,
                            selected=True,
                        )
                    )

        return SelectNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            field_operations=field_operations,
            select_all_unknown=True,
            conversion_notes=["Arrange: column reordering maps to select with reorder operations."],
        )
