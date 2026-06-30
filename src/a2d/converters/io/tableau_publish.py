"""Converter for Alteryx PublishToTableauServer -> WriteNode with Tableau guidance."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.ir.nodes import IRNode, WriteNode
from a2d.parser.schema import ParsedNode


def _extract_value(cfg: dict, name: str) -> str:
    """Extract a named value from the PublishToTableauServer config format."""
    values = cfg.get("Value", [])
    if isinstance(values, dict):
        values = [values]
    if isinstance(values, list):
        for item in values:
            if isinstance(item, dict) and item.get("@name") == name:
                return item.get("#text", "")
    return ""


@ConverterRegistry.register
class TableauPublishConverter(ToolConverter):
    """Converts Alteryx PublishToTableauServer to :class:`WriteNode`.

    In Databricks, instead of publishing directly to Tableau Server,
    the recommended pattern is to write data to a Delta table and
    connect Tableau to it via the Databricks connector.
    """

    @property
    def supported_tool_types(self) -> list[str]:
        return ["PublishToTableauServer"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        server_url = _extract_value(cfg, "serverUrl")
        site = _extract_value(cfg, "site")
        datasource = _extract_value(cfg, "datasourceName")

        # Build a meaningful table name from the Tableau datasource name
        table_name = datasource or f"tableau_output_{parsed_node.tool_id}"
        # Sanitize for use as a table name
        table_name = table_name.replace("-", "_").replace(" ", "_").lower()

        notes = [
            f"Tableau Server: {server_url}" if server_url else "",
            f"Site: {site}" if site else "",
            f"Datasource: {datasource}" if datasource else "",
            "Databricks approach: Write to Delta table, then connect Tableau via Databricks connector.",
        ]

        return WriteNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            conversion_confidence=0.7,
            conversion_notes=[n for n in notes if n],
            destination_type="database",
            table_name=f"{config.catalog_name}.{config.schema_name}.{table_name}",
            file_format="delta",
            write_mode="overwrite",
        )
