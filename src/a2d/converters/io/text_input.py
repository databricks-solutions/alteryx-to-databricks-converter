"""Converter for Alteryx TextInput tool -> LiteralDataNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import ensure_list
from a2d.ir.nodes import IRNode, LiteralDataNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class TextInputConverter(ToolConverter):
    """Converts Alteryx TextInput to :class:`LiteralDataNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["TextInput"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        # -- Extract field names and types -----------------------------------
        # Alteryx TextInput stores fields in a <Fields> element with child
        # <Field> entries.  After element_to_dict, this becomes:
        #   cfg["Fields"]["Field"] -> list of dicts with @name, @type
        field_names: list[str] = []
        field_types: list[str] = []
        fields_section = cfg.get("Fields", {})
        if isinstance(fields_section, dict):
            raw_fields = ensure_list(fields_section.get("Field", []))
            for f in raw_fields:
                if isinstance(f, dict):
                    field_names.append(f.get("@name", ""))
                    field_types.append(f.get("@type", "V_WString"))

        # -- Extract data rows -----------------------------------------------
        # Data is stored as <Data> with child <r> rows, each containing <c>
        # cell values.  element_to_dict turns this into:
        #   cfg["Data"]["r"] -> list of dicts each with "c" -> list of values
        data_rows: list[list[str]] = []
        data_section = cfg.get("Data", {})
        if isinstance(data_section, dict):
            raw_rows = ensure_list(data_section.get("r", []))
            for row in raw_rows:
                if isinstance(row, dict):
                    cells = ensure_list(row.get("c", []))
                    data_rows.append([str(c) if c is not None else "" for c in cells])
                elif isinstance(row, str):
                    # Single-column shorthand
                    data_rows.append([row])

        return LiteralDataNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            num_fields=len(field_names),
            num_records=len(data_rows),
            field_names=field_names,
            field_types=field_types,
            data_rows=data_rows,
        )
