"""Converter for Alteryx Widget tools -> WidgetNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import CommentNode, IRNode, WidgetNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class WidgetConverter(ToolConverter):
    """Converts Alteryx widget tools to :class:`WidgetNode`.

    Alteryx Analytic Apps use widgets (CheckBox, Date, DropDown, etc.) for user
    input. These map to Databricks notebook widgets.
    """

    @property
    def supported_tool_types(self) -> list[str]:
        return [
            "CheckBox",
            "Date",
            "DropDown",
            "FileInput",
            "ListBox",
            "NumericUpDown",
            "RadioButton",
            "TextBox",
            "Tree",
        ]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        # TextBox with "Text" key but no "FieldName" is an annotation, not a widget
        if parsed_node.tool_type == "TextBox" and "Text" in cfg and not cfg.get("FieldName"):
            text = safe_get(cfg, "Text", "")
            return CommentNode(
                node_id=parsed_node.tool_id,
                original_tool_type=parsed_node.tool_type,
                original_plugin_name=parsed_node.plugin_name,
                annotation=parsed_node.annotation,
                position=parsed_node.position,
                comment_text=text,
            )

        # Map Alteryx tool type to widget type
        widget_type_map = {
            "CheckBox": "checkbox",
            "Date": "date",
            "DropDown": "dropdown",
            "FileInput": "file_input",
            "ListBox": "listbox",
            "NumericUpDown": "numeric",
            "RadioButton": "radio",
            "TextBox": "textbox",
            "Tree": "tree",
        }
        widget_type = widget_type_map.get(parsed_node.tool_type, parsed_node.tool_type.lower())

        field_name = safe_get(cfg, "FieldName", safe_get(cfg, "Name", ""))
        label = safe_get(cfg, "Label", safe_get(cfg, "Question", ""))
        default_value = safe_get(cfg, "DefaultValue", safe_get(cfg, "Default", ""))

        # Extract options for dropdown/listbox/radio widgets
        options: list[str] = []
        options_raw = cfg.get("Options", cfg.get("Values", cfg.get("Items", [])))

        if isinstance(options_raw, list):
            for option_item in options_raw:
                if isinstance(option_item, dict):
                    option_value = safe_get(option_item, "value", safe_get(option_item, "name", ""))
                elif isinstance(option_item, str):
                    option_value = option_item
                else:
                    continue

                if option_value:
                    options.append(option_value)
        elif isinstance(options_raw, str):
            # Comma-separated options
            options = [o.strip() for o in options_raw.split(",") if o.strip()]

        return WidgetNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            widget_type=widget_type,
            field_name=field_name,
            label=label,
            default_value=default_value,
            options=options,
            conversion_notes=[f"{parsed_node.tool_type}: UI widget maps to Databricks dbutils.widgets.{widget_type}()"],
        )
