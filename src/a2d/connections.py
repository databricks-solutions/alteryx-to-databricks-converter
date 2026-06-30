"""Connection mapping configuration for Alteryx-to-Databricks migration.

Maps Alteryx connection names (ODBC, OLEDB, file paths) to Databricks
Unity Catalog locations (catalog.schema.table).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("a2d.connections")


@dataclass(frozen=True)
class ConnectionMapping:
    """A single connection mapping from Alteryx to Databricks."""

    alteryx_name: str
    catalog: str = ""
    schema: str = ""
    table_prefix: str = ""

    def resolve_table(self, table_name: str) -> str:
        """Resolve a table name to a fully qualified Databricks path."""
        prefix = f"{self.table_prefix}{table_name}" if self.table_prefix else table_name
        parts = [p for p in (self.catalog, self.schema, prefix) if p]
        return ".".join(parts)


@dataclass
class ConnectionMappingConfig:
    """Collection of connection mappings with defaults."""

    mappings: dict[str, ConnectionMapping] = field(default_factory=dict)
    default_catalog: str = "main"
    default_schema: str = "default"

    def resolve(self, connection_name: str, table_name: str = "") -> str:
        """Resolve a connection name to a Databricks table path.

        Falls back to default catalog/schema if no explicit mapping exists.
        """
        mapping = self.mappings.get(connection_name)
        if mapping:
            return mapping.resolve_table(table_name)

        # Fallback to defaults
        parts = [p for p in (self.default_catalog, self.default_schema, table_name) if p]
        return ".".join(parts)

    def get_unmapped_connections(self, connection_names: set[str]) -> list[str]:
        """Return connection names that have no explicit mapping."""
        return sorted(name for name in connection_names if name not in self.mappings)


def load_connection_mapping(path: Path) -> ConnectionMappingConfig:
    """Load a connection mapping configuration from a YAML file.

    Expected YAML structure:
        default_catalog: main
        default_schema: default
        mappings:
          "ODBCConnection1":
            catalog: analytics
            schema: raw
            table_prefix: "src_"
          "FileInput_Sales":
            catalog: main
            schema: bronze

    Raises:
        FileNotFoundError: If the path does not exist.
        ValueError: If the YAML is malformed or missing required fields.
    """
    if not path.exists():
        raise FileNotFoundError(f"Connection mapping file not found: {path}")

    try:
        import yaml
    except ImportError as exc:
        raise ImportError("PyYAML is required for connection mapping. Install with: pip install pyyaml") from exc

    text = path.read_text(encoding="utf-8")
    try:
        data: dict[str, Any] = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in connection mapping file: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("Connection mapping file must be a YAML dictionary")

    default_catalog = str(data.get("default_catalog") or "main")
    default_schema = str(data.get("default_schema") or "default")

    mappings: dict[str, ConnectionMapping] = {}
    raw_mappings = data.get("mappings", {})
    if not isinstance(raw_mappings, dict):
        raise ValueError("'mappings' must be a dictionary")

    for name, spec in raw_mappings.items():
        if not isinstance(spec, dict):
            raise ValueError(f"Mapping for '{name}' must be a dictionary")
        mappings[str(name)] = ConnectionMapping(
            alteryx_name=str(name),
            catalog=str(spec.get("catalog") or default_catalog),
            schema=str(spec.get("schema") or default_schema),
            table_prefix=str(spec.get("table_prefix") or ""),
        )

    return ConnectionMappingConfig(
        mappings=mappings,
        default_catalog=default_catalog,
        default_schema=default_schema,
    )
