"""Converter for Alteryx OutputData (DbFileOutput) tool -> WriteNode."""

from __future__ import annotations

import html
import os

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get_nested
from a2d.ir.nodes import IRNode, WriteNode
from a2d.parser.schema import ParsedNode

_EXT_TO_FORMAT: dict[str, str] = {
    ".csv": "csv",
    ".txt": "csv",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".yxdb": "yxdb",
    ".json": "json",
    ".parquet": "parquet",
    ".avro": "avro",
    ".dbf": "dbf",
    ".hyper": "hyper",
}

# Alteryx option values -> canonical write modes
_WRITE_MODE_MAP: dict[str, str] = {
    "Overwrite": "overwrite",
    "Append": "append",
    "CreateNew": "create_new",
    "Overwrite File (Remove)": "overwrite",
    "Delete Data & Append": "overwrite",
    "Create": "overwrite",
}


@ConverterRegistry.register
class OutputDataConverter(ToolConverter):
    """Converts Alteryx OutputData (DbFileOutput) to :class:`WriteNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Output"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        # File element can be a dict with @FilePath/@FileFormat attributes,
        # #text (inline value), or a plain string
        file_info = cfg.get("File", "")
        if isinstance(file_info, dict):
            file_path = file_info.get("@FilePath", "") or file_info.get("FilePath", "") or file_info.get("#text", "")
        else:
            file_path = str(file_info) if file_info else ""
        if not file_path:
            file_path = safe_get_nested(cfg, "FileName")
        connection_string = safe_get_nested(cfg, "Connection")
        table_name = safe_get_nested(cfg, "TableName")

        # Detect ODBC/OLEDB connection strings encoded in file_path
        if file_path and ("odbc:" in file_path.lower() or "oledb:" in file_path.lower()):
            destination_type = "database"
            if "|||" in file_path:
                # Pattern: "odbc:DSN=...|||\"Schema\".\"Table\""
                parts = file_path.split("|||", 1)
                connection_string = connection_string or parts[0]
                table_name = table_name or parts[1].strip().strip('"')
            elif not connection_string:
                connection_string = file_path
            file_format = ""
        else:
            # Detect format from extension — strip Alteryx "|||SheetName" selector
            # first so xlsx is detected even when a sheet name is appended
            # (e.g. "/path/Day0.xlsx|||Sheet1").
            _clean_fp = file_path.split("|||")[0] if file_path and "|||" in file_path else file_path
            _, ext = os.path.splitext(_clean_fp.lower()) if _clean_fp else ("", "")
            file_format = _EXT_TO_FORMAT.get(ext, ext.lstrip(".") if ext else "")
            destination_type = "database" if connection_string else "file"

        # Write mode - check several possible config keys
        raw_mode = (
            safe_get_nested(cfg, "WriteMode")
            or safe_get_nested(cfg, "Mode")
            or safe_get_nested(cfg, "OutputMode")
            or safe_get_nested(cfg, "FormatSpecificOptions", "OutputOption")
        )
        write_mode = _WRITE_MODE_MAP.get(raw_mode, "overwrite")

        # CSV options
        has_header = safe_get_nested(cfg, "HeaderRow", default="True").lower() != "false"
        delimiter = safe_get_nested(cfg, "Delimiter", default=",")
        if delimiter == "\\t":
            delimiter = "\t"
        encoding = safe_get_nested(cfg, "CodePage", default="utf-8")

        # Partition fields (Alteryx OutputOption > Partitions)
        partition_raw = safe_get_nested(cfg, "Partitions") or safe_get_nested(cfg, "PartitionFields")
        partition_fields: list[str] = []
        if partition_raw:
            if isinstance(partition_raw, str):
                partition_fields = [f.strip() for f in partition_raw.split(",") if f.strip()]
            elif isinstance(partition_raw, list):
                partition_fields = [str(f) for f in partition_raw]

        # Compression codec
        compression: str | None = (
            safe_get_nested(cfg, "Compression") or safe_get_nested(cfg, "CompressionCodec") or None
        )
        if compression and compression.lower() in ("none", ""):
            compression = None

        if file_path:
            file_path = html.unescape(file_path)

        notes: list[str] = []
        confidence = 1.0
        if destination_type == "database":
            notes.append("Database destination; connection string needs manual mapping.")
            confidence = 0.7
        if file_format == "yxdb":
            notes.append("Writing .yxdb not supported; recommend Parquet or Delta.")
            confidence = min(confidence, 0.6)

        return WriteNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            conversion_confidence=confidence,
            conversion_notes=notes,
            destination_type=destination_type,
            file_path=file_path,
            connection_string=connection_string,
            table_name=table_name,
            file_format=file_format,
            write_mode=write_mode,
            has_header=has_header,
            delimiter=delimiter,
            encoding=encoding,
            partition_fields=partition_fields,
            compression=compression,
        )
