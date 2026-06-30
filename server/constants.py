"""Shared constants for the server layer."""

from __future__ import annotations

from a2d.config import OutputFormat

FORMAT_MAP: dict[str, OutputFormat] = {
    "pyspark": OutputFormat.PYSPARK,
    "dlt": OutputFormat.DLT,
    "sql": OutputFormat.SQL,
    "lakeflow": OutputFormat.LAKEFLOW,
}
