"""Converter for Alteryx Download tool -> DownloadNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import ensure_list, safe_get
from a2d.ir.nodes import DownloadNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class DownloadConverter(ToolConverter):
    """Converts Alteryx Download to :class:`DownloadNode`.

    The Download tool makes HTTP requests.  In Databricks this maps to
    ``requests`` in a UDF or ``spark.read.format("http")``.
    """

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Download"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        url_field = safe_get(cfg, "URLField")
        url_static = safe_get(cfg, "URL")
        method = safe_get(cfg, "Method", default="GET").upper()
        if method not in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"):
            method = "GET"

        body = safe_get(cfg, "Body") or safe_get(cfg, "Payload")
        output_field = safe_get(cfg, "OutputField", default="DownloadData")
        if not output_field:
            output_field = "DownloadData"

        timeout_str = safe_get(cfg, "Timeout", default="30")
        connection_timeout = int(timeout_str) if timeout_str.isdigit() else 30

        retries_str = safe_get(cfg, "MaxRetries", default="0")
        max_retries = int(retries_str) if retries_str.isdigit() else 0

        # Headers
        headers: dict[str, str] = {}
        headers_section = cfg.get("Headers", {})
        if isinstance(headers_section, dict):
            raw = ensure_list(headers_section.get("Header", []))
            for h in raw:
                if isinstance(h, dict):
                    name = safe_get(h, "@name")
                    value = safe_get(h, "@value") or safe_get(h, "#text")
                    if name:
                        headers[name] = value

        return DownloadNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            url_field=url_field,
            url_static=url_static,
            method=method,
            headers=headers,
            body=body,
            output_field=output_field,
            connection_timeout=connection_timeout,
            max_retries=max_retries,
            conversion_confidence=0.4,
            conversion_notes=[
                "Download tool requires manual conversion to requests library or HTTP connector.",
                "Consider using Databricks Secrets for any API keys.",
            ],
        )
