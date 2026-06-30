"""Converter for Alteryx cloud storage tools -> CloudStorageNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import CloudStorageNode, IRNode
from a2d.parser.schema import ParsedNode


def _map_tool_to_provider_and_direction(tool_type: str) -> tuple[str, str]:
    """Map tool type to cloud provider and direction."""
    tool_lower = tool_type.lower()

    if "s3" in tool_lower or "amazon" in tool_lower:
        provider = "s3"
    elif "azure" in tool_lower or "blob" in tool_lower:
        provider = "azure"
    elif "sharepoint" in tool_lower:
        provider = "sharepoint"
    else:
        provider = "unknown"

    if "download" in tool_lower or "input" in tool_lower:
        direction = "input"
    elif "upload" in tool_lower or "output" in tool_lower:
        direction = "output"
    else:
        direction = "input"

    return provider, direction


@ConverterRegistry.register
class CloudStorageConverter(ToolConverter):
    """Converts Alteryx cloud storage tools to :class:`CloudStorageNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return [
            "AmazonS3Download",
            "AmazonS3Upload",
            "AzureBlobInput",
            "AzureBlobOutput",
            "SharePointInput",
        ]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        provider, direction = _map_tool_to_provider_and_direction(parsed_node.tool_type)

        # Extract bucket/container from config - handle @-prefixed dict keys from XML attributes
        bucket_or_container = ""
        if isinstance(cfg.get("Bucket"), dict):
            bucket_or_container = cfg.get("Bucket", {}).get("@name", "")
        else:
            bucket_or_container = safe_get(cfg, "Bucket")

        if not bucket_or_container:
            if isinstance(cfg.get("Container"), dict):
                bucket_or_container = cfg.get("Container", {}).get("@name", "")
            else:
                bucket_or_container = safe_get(cfg, "Container")

        # Extract path - handle @-prefixed dict keys
        path = ""
        path = cfg.get("Path", {}).get("@value", "") if isinstance(cfg.get("Path"), dict) else safe_get(cfg, "Path")

        if not path:
            if isinstance(cfg.get("FilePath"), dict):
                path = cfg.get("FilePath", {}).get("@value", "")
            else:
                path = safe_get(cfg, "FilePath")

        # Extract file format
        file_format = safe_get(cfg, "FileFormat", "csv").lower()
        if not file_format or file_format == "":
            file_format = safe_get(cfg, "Format", "csv").lower()

        # Build auth config from various credential fields
        auth_config = {}
        access_key = safe_get(cfg, "AccessKey")
        secret_key = safe_get(cfg, "SecretKey")
        connection_string = safe_get(cfg, "ConnectionString")

        if access_key:
            auth_config["access_key"] = access_key
        if secret_key:
            auth_config["secret_key"] = secret_key
        if connection_string:
            auth_config["connection_string"] = connection_string

        return CloudStorageNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            provider=provider,
            direction=direction,
            bucket_or_container=bucket_or_container,
            path=path,
            file_format=file_format,
            auth_config=auth_config,
            conversion_notes=[f"Cloud storage {direction} from {provider}; credentials need manual configuration."],
        )
