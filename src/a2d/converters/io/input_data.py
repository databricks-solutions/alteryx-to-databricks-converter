"""Converter for Alteryx InputData (DbFileInput) tool -> ReadNode."""

from __future__ import annotations

import html
import os

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get_nested
from a2d.ir.nodes import IRNode, ReadNode
from a2d.parser.schema import ParsedNode

# Map of common Alteryx file extensions to our canonical format strings
_EXT_TO_FORMAT: dict[str, str] = {
    ".csv": "csv",
    ".txt": "csv",
    ".tsv": "csv",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".yxdb": "yxdb",
    ".json": "json",
    ".parquet": "parquet",
    ".avro": "avro",
    ".sas7bdat": "sas",
    ".dbf": "dbf",
}


def _detect_format(file_path: str) -> str:
    """Detect file format from the file extension.

    Strips any sheet selector suffix (e.g. ``|||`SheetName$```) before
    inspecting the extension so that Excel paths with sheet references are
    correctly identified as ``xlsx``.
    """
    # Strip Alteryx pipe-delimited sheet/table selector before extension detection
    clean_path = file_path.split("|||")[0] if "|||" in file_path else file_path
    _, ext = os.path.splitext(clean_path.lower())
    return _EXT_TO_FORMAT.get(ext, ext.lstrip(".") if ext else "unknown")


def _detect_source_type(file_path: str, connection_string: str) -> str:
    """Determine whether this is a file or database source."""
    if connection_string:
        return "database"
    return "file"


@ConverterRegistry.register
class InputDataConverter(ToolConverter):
    """Converts Alteryx InputData (DbFileInput) to :class:`ReadNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Input"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        # File path / connection - File element can be dict with @FilePath attr,
        # #text (inline value), or a plain string
        file_info = cfg.get("File", "")
        file_path = ""
        if isinstance(file_info, dict):
            file_path = file_info.get("@FilePath", "") or file_info.get("FilePath", "") or file_info.get("#text", "")
        else:
            file_path = str(file_info) if file_info else ""
        if not file_path:
            file_path = safe_get_nested(cfg, "FileName")
        connection_string = safe_get_nested(cfg, "Connection")
        table_name = safe_get_nested(cfg, "TableName")
        query = safe_get_nested(cfg, "Query")

        # Handle Alteryx DB connection format: "aka:CONNECTION_NAME|||<sql>"
        if file_path and file_path.startswith("aka:"):
            parts = file_path.split("|||", 1)
            connection_string = connection_string or parts[0]  # "aka:NAME"
            if len(parts) > 1 and parts[1].strip():
                query = query or parts[1].strip()
            file_path = ""

        # Handle ODBC connection format: "odbc:DSN=...;...|||<sql>"
        # FileFormat=23 in Alteryx means ODBC query source.
        if file_path and file_path.lower().startswith("odbc:"):
            parts = file_path.split("|||", 1)
            connection_string = connection_string or parts[0]
            if len(parts) > 1 and parts[1].strip():
                query = query or parts[1].strip()
            file_path = ""

        # Detect format
        file_format = _detect_format(file_path) if file_path else ""
        source_type = _detect_source_type(file_path, connection_string)

        # CSV-specific options
        has_header = safe_get_nested(cfg, "HeaderRow", default="True").lower() != "false"
        delimiter = safe_get_nested(cfg, "Delimiter", default=",")
        # Alteryx uses \t representation for tab delimiters
        if delimiter == "\\t":
            delimiter = "\t"
        encoding = safe_get_nested(cfg, "CodePage", default="utf-8")

        # Record limit
        record_limit_str = safe_get_nested(cfg, "RecordLimit")
        record_limit = int(record_limit_str) if record_limit_str and record_limit_str.isdigit() else None

        # Decode any HTML entities in path
        if file_path:
            file_path = html.unescape(file_path)

        notes: list[str] = []
        confidence = 1.0

        if source_type == "database":
            notes.append("Database source detected; connection string needs manual mapping.")
            confidence = 0.7

        if file_format == "yxdb":
            notes.append("Alteryx .yxdb format requires conversion to Parquet or Delta.")
            confidence = min(confidence, 0.8)

        return ReadNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            conversion_confidence=confidence,
            conversion_notes=notes,
            source_type=source_type,
            file_path=file_path,
            connection_string=connection_string,
            table_name=table_name,
            query=query,
            file_format=file_format,
            has_header=has_header,
            delimiter=delimiter,
            encoding=encoding,
            record_limit=record_limit,
        )
