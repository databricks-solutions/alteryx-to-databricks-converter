"""Converter for Alteryx EmailOutput tool -> EmailOutputNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import EmailOutputNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class EmailOutputConverter(ToolConverter):
    """Converts Alteryx EmailOutput tool to :class:`EmailOutputNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["EmailOutput"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        # Extract email configuration
        to_field = safe_get(cfg, "ToField", safe_get(cfg, "To", ""))
        subject_field = safe_get(cfg, "SubjectField", safe_get(cfg, "Subject", ""))
        body_field = safe_get(cfg, "BodyField", safe_get(cfg, "Body", ""))
        smtp_server = safe_get(cfg, "SMTPServer", safe_get(cfg, "Server", ""))
        attachment_field = safe_get(cfg, "AttachmentField", safe_get(cfg, "Attachment", ""))

        return EmailOutputNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            to_field=to_field,
            subject_field=subject_field,
            body_field=body_field,
            smtp_server=smtp_server,
            attachment_field=attachment_field,
            conversion_notes=[
                "Email output requires SMTP configuration in Databricks; consider using workspace notifications."
            ],
        )
