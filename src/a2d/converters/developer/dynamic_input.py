"""Converter for Alteryx DynamicInput tool -> DynamicInputNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import DynamicInputNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class DynamicInputConverter(ToolConverter):
    """Converts Alteryx DynamicInput tool to :class:`DynamicInputNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["DynamicInput"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        # --- File-pattern mode fields (legacy) ---
        file_path_pattern = safe_get(cfg, "FilePath", safe_get(cfg, "PathField", ""))
        file_format = safe_get(cfg, "FileFormat", "csv").lower()
        template_file = safe_get(cfg, "TemplateFile", safe_get(cfg, "Template", ""))

        # --- ModifySQL / SQL mode fields ---
        mode = safe_get(cfg, "Mode", "")

        # Template SQL lives inside InputConfiguration > Configuration > File
        inner_cfg = cfg.get("InputConfiguration") or {}
        if isinstance(inner_cfg, dict):
            inner_cfg = inner_cfg.get("Configuration") or {}
        file_info = inner_cfg.get("File", "") if isinstance(inner_cfg, dict) else ""

        # File element may be a dict with #text or a plain string
        if isinstance(file_info, dict):
            raw = file_info.get("#text", "") or file_info.get("@FilePath", "") or file_info.get("FilePath", "")
        else:
            raw = str(file_info) if file_info else ""

        template_query = ""
        template_connection = ""
        if raw and (raw.startswith("aka:") or raw.lower().startswith("odbc:")):
            parts = raw.split("|||", 1)
            template_connection = parts[0].strip()
            template_query = parts[1].strip() if len(parts) > 1 else ""

        # --- Parse Modifications list ---
        mods_raw = cfg.get("Modifications") or {}
        if isinstance(mods_raw, dict):
            mods_raw = mods_raw.get("Modify", [])
        if isinstance(mods_raw, dict):
            mods_raw = [mods_raw]
        modifications = []
        for m in mods_raw or []:
            if isinstance(m, dict):
                field_name = m.get("Field", "") or m.get("@Annotation", "")
                replace_text = m.get("ReplaceText", "")
                if field_name:
                    modifications.append({"field": field_name, "replace_text": replace_text})

        notes = ["DynamicInput: file list may need adjustment for Databricks paths."]
        if mode == "ModifySQL" and template_query:
            notes = ["DynamicInput (ModifySQL): parameterized SQL loop generated — map connection to Databricks."]

        return DynamicInputNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            file_path_pattern=file_path_pattern,
            file_format=file_format,
            template_file=template_file,
            mode=mode,
            template_query=template_query,
            template_connection=template_connection,
            modifications=modifications,
            conversion_notes=notes,
        )
