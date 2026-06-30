"""Tests for the connection mapping module."""

from __future__ import annotations

from pathlib import Path

import pytest

from a2d.connections import (
    ConnectionMapping,
    ConnectionMappingConfig,
    load_connection_mapping,
)

# ── ConnectionMapping.resolve_table ──────────────────────────────────────


class TestConnectionMappingResolveTable:
    def test_resolve_with_catalog_schema_prefix(self):
        mapping = ConnectionMapping(
            alteryx_name="conn1",
            catalog="analytics",
            schema="raw",
            table_prefix="src_",
        )
        result = mapping.resolve_table("orders")
        assert result == "analytics.raw.src_orders"

    def test_resolve_without_prefix(self):
        mapping = ConnectionMapping(
            alteryx_name="conn1",
            catalog="main",
            schema="bronze",
        )
        result = mapping.resolve_table("customers")
        assert result == "main.bronze.customers"

    def test_resolve_catalog_only(self):
        mapping = ConnectionMapping(
            alteryx_name="conn1",
            catalog="main",
        )
        result = mapping.resolve_table("events")
        assert result == "main.events"

    def test_resolve_empty_table_name(self):
        mapping = ConnectionMapping(
            alteryx_name="conn1",
            catalog="main",
            schema="raw",
        )
        result = mapping.resolve_table("")
        assert result == "main.raw"

    def test_resolve_all_empty(self):
        mapping = ConnectionMapping(alteryx_name="conn1")
        result = mapping.resolve_table("")
        assert result == ""


# ── ConnectionMappingConfig.resolve ──────────────────────────────────────


class TestConnectionMappingConfigResolve:
    def test_resolve_with_explicit_mapping(self):
        config = ConnectionMappingConfig(
            mappings={
                "ODBCConn": ConnectionMapping(
                    alteryx_name="ODBCConn",
                    catalog="analytics",
                    schema="raw",
                    table_prefix="src_",
                ),
            },
            default_catalog="main",
            default_schema="default",
        )
        result = config.resolve("ODBCConn", "orders")
        assert result == "analytics.raw.src_orders"

    def test_resolve_falls_back_to_defaults(self):
        config = ConnectionMappingConfig(
            mappings={},
            default_catalog="main",
            default_schema="default",
        )
        result = config.resolve("UnmappedConnection", "sales")
        assert result == "main.default.sales"

    def test_resolve_fallback_without_table_name(self):
        config = ConnectionMappingConfig(
            mappings={},
            default_catalog="main",
            default_schema="bronze",
        )
        result = config.resolve("SomeConn")
        assert result == "main.bronze"


# ── ConnectionMappingConfig.get_unmapped_connections ─────────────────────


class TestGetUnmappedConnections:
    def test_returns_unmapped(self):
        config = ConnectionMappingConfig(
            mappings={
                "ConnA": ConnectionMapping(alteryx_name="ConnA", catalog="cat"),
            },
        )
        unmapped = config.get_unmapped_connections({"ConnA", "ConnB", "ConnC"})
        assert unmapped == ["ConnB", "ConnC"]

    def test_all_mapped(self):
        config = ConnectionMappingConfig(
            mappings={
                "ConnA": ConnectionMapping(alteryx_name="ConnA"),
                "ConnB": ConnectionMapping(alteryx_name="ConnB"),
            },
        )
        unmapped = config.get_unmapped_connections({"ConnA", "ConnB"})
        assert unmapped == []

    def test_empty_input(self):
        config = ConnectionMappingConfig(
            mappings={
                "ConnA": ConnectionMapping(alteryx_name="ConnA"),
            },
        )
        unmapped = config.get_unmapped_connections(set())
        assert unmapped == []


# ── load_connection_mapping ──────────────────────────────────────────────


class TestLoadConnectionMapping:
    def test_valid_yaml(self, tmp_path: Path):
        yaml_content = """\
default_catalog: analytics
default_schema: bronze
mappings:
  ODBCConnection1:
    catalog: analytics
    schema: raw
    table_prefix: "src_"
  FileInput_Sales:
    catalog: main
    schema: bronze
"""
        yaml_file = tmp_path / "connections.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")

        config = load_connection_mapping(yaml_file)

        assert config.default_catalog == "analytics"
        assert config.default_schema == "bronze"
        assert len(config.mappings) == 2
        assert "ODBCConnection1" in config.mappings
        assert config.mappings["ODBCConnection1"].catalog == "analytics"
        assert config.mappings["ODBCConnection1"].schema == "raw"
        assert config.mappings["ODBCConnection1"].table_prefix == "src_"
        assert config.mappings["FileInput_Sales"].catalog == "main"
        assert config.mappings["FileInput_Sales"].schema == "bronze"

    def test_valid_yaml_defaults(self, tmp_path: Path):
        """YAML with no explicit default_catalog/default_schema uses 'main'/'default'."""
        yaml_content = """\
mappings:
  Conn1:
    catalog: mycat
"""
        yaml_file = tmp_path / "connections.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")

        config = load_connection_mapping(yaml_file)

        assert config.default_catalog == "main"
        assert config.default_schema == "default"
        assert config.mappings["Conn1"].catalog == "mycat"
        # schema should inherit default_schema since not specified
        assert config.mappings["Conn1"].schema == "default"

    def test_empty_yaml(self, tmp_path: Path):
        """An empty YAML file produces an empty config with defaults."""
        yaml_file = tmp_path / "connections.yaml"
        yaml_file.write_text("", encoding="utf-8")

        config = load_connection_mapping(yaml_file)

        assert config.default_catalog == "main"
        assert config.default_schema == "default"
        assert config.mappings == {}

    def test_missing_file_raises(self, tmp_path: Path):
        missing = tmp_path / "does_not_exist.yaml"
        with pytest.raises(FileNotFoundError, match="Connection mapping file not found"):
            load_connection_mapping(missing)

    def test_invalid_yaml_raises(self, tmp_path: Path):
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("{{invalid: yaml: [", encoding="utf-8")

        with pytest.raises(ValueError, match="Invalid YAML"):
            load_connection_mapping(yaml_file)

    def test_non_dict_root_raises(self, tmp_path: Path):
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("- item1\n- item2\n", encoding="utf-8")

        with pytest.raises(ValueError, match="must be a YAML dictionary"):
            load_connection_mapping(yaml_file)

    def test_non_dict_mappings_raises(self, tmp_path: Path):
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("mappings:\n  - not_a_dict\n", encoding="utf-8")

        with pytest.raises(ValueError, match="'mappings' must be a dictionary"):
            load_connection_mapping(yaml_file)

    def test_non_dict_mapping_entry_raises(self, tmp_path: Path):
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("mappings:\n  ConnA: not_a_dict\n", encoding="utf-8")

        with pytest.raises(ValueError, match="Mapping for 'ConnA' must be a dictionary"):
            load_connection_mapping(yaml_file)

    def test_resolve_round_trip(self, tmp_path: Path):
        """Load from YAML and then resolve a table to verify end-to-end."""
        yaml_content = """\
default_catalog: warehouse
default_schema: staging
mappings:
  ProdDB:
    catalog: prod
    schema: public
    table_prefix: "tbl_"
"""
        yaml_file = tmp_path / "connections.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")

        config = load_connection_mapping(yaml_file)

        # Mapped connection
        assert config.resolve("ProdDB", "users") == "prod.public.tbl_users"
        # Unmapped connection falls back to defaults
        assert config.resolve("UnknownConn", "events") == "warehouse.staging.events"
