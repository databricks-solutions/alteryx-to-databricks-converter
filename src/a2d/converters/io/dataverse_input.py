"""Converter for Microsoft Dataverse / Power Platform input tool -> ReadNode.

Alteryx ships a versioned ``DataverseInput_<version>`` SDK plugin that reads
tables from Microsoft Dataverse. There is no native Spark Dataverse reader, so
we emit a stub ``ReadNode`` annotated with ``source_type="dataverse"`` that
generators turn into a TODO with the original Alteryx connection metadata
preserved as comments.
"""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import IRNode, ReadNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class DataverseInputConverter(ToolConverter):
    """Convert Alteryx DataverseInput tool to a stub :class:`ReadNode`.

    Properties handled (best-effort, pass-through to comments):
      - LogicalName / LogicalCollectionName: Dataverse table identifier.
      - ConnectionId: Alteryx-managed connection alias.
      - InstanceUrl: Dataverse environment URL.
      - Query / CustomODataQuery: optional OData query.
      - Columns: column subset.
      - MaxNumberOfRows: optional row cap.
    """

    @property
    def supported_tool_types(self) -> list[str]:
        return ["DataverseInput"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        logical_name = safe_get(cfg, "LogicalName") or safe_get(cfg, "LogicalCollectionName") or ""
        connection_id = safe_get(cfg, "ConnectionId")
        instance_url = safe_get(cfg, "InstanceUrl")
        query = safe_get(cfg, "Query") or safe_get(cfg, "CustomODataQuery") or ""
        max_rows_raw = safe_get(cfg, "MaxNumberOfRows")

        record_limit: int | None = None
        if max_rows_raw:
            try:
                parsed_limit = int(str(max_rows_raw).strip())
                if parsed_limit > 0:
                    record_limit = parsed_limit
            except (TypeError, ValueError):
                record_limit = None

        # Build a connection_string-style descriptor that the generators surface
        # as a comment; we keep this human-readable rather than functional.
        descriptor_parts: list[str] = []
        if instance_url:
            descriptor_parts.append(f"instance={instance_url}")
        if connection_id:
            descriptor_parts.append(f"connection_id={connection_id}")
        connection_descriptor = "dataverse://" + ";".join(descriptor_parts) if descriptor_parts else "dataverse://"

        notes = [
            "Microsoft Dataverse input — no native Databricks reader.",
            "Replace with one of: Power Platform → ADLS export + spark.read, "
            "Fivetran/Airbyte Dataverse connector, or a custom OData REST ingest.",
        ]
        if logical_name:
            notes.append(f"Dataverse table (LogicalName): {logical_name}")
        if query:
            notes.append(f"Original OData query: {query}")

        return ReadNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            source_type="dataverse",
            connection_string=connection_descriptor,
            table_name=logical_name,
            query=query,
            file_format="dataverse",
            record_limit=record_limit,
            conversion_confidence=0.4,
            conversion_method="template",
            conversion_notes=notes,
        )
