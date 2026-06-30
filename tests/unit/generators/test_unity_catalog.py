"""Tests for the Unity Catalog DDL generator."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from a2d.config import ConversionConfig
from a2d.generators.unity_catalog import _DDL_FORMAT_MAP, UnityCatalogGenerator
from a2d.ir.nodes import (
    CloudStorageNode,
    DynamicInputNode,
    FilterNode,
    ReadNode,
    WriteNode,
)


@pytest.fixture
def config() -> ConversionConfig:
    return ConversionConfig(catalog_name="my_catalog", schema_name="my_schema")


@pytest.fixture
def generator(config: ConversionConfig) -> UnityCatalogGenerator:
    return UnityCatalogGenerator(config)


def _make_dag_mock(nodes: list) -> MagicMock:
    """Create a mock DAG whose topological_sort returns the given nodes.

    The UnityCatalogGenerator calls dag.topological_sort() which is not
    a method on WorkflowDAG (the method is topological_order). We mock
    the DAG to provide topological_sort for the generator to call.
    """
    dag = MagicMock()
    dag.topological_sort.return_value = nodes
    return dag


class TestReadNodeDDL:
    """Tests for DDL generation from ReadNode."""

    def test_database_source_creates_table(self, generator: UnityCatalogGenerator):
        """ReadNode with database source should produce CREATE TABLE."""
        node = ReadNode(
            node_id=1,
            source_type="database",
            connection_string="server=prod_db",
            table_name="customers",
        )

        stmt = generator._read_node_ddl(node)

        assert stmt is not None
        assert "CREATE TABLE IF NOT EXISTS" in stmt
        assert "customers" in stmt
        assert "server=prod_db" in stmt

    def test_database_source_uses_connection_mapping(self, generator: UnityCatalogGenerator):
        """Database ReadNode should resolve via connection mapping to fully qualified name."""
        node = ReadNode(
            node_id=1,
            source_type="database",
            connection_string="my_conn",
            table_name="orders",
        )

        stmt = generator._read_node_ddl(node)

        assert stmt is not None
        # Default mapping: catalog.schema.table
        assert "my_catalog.my_schema.orders" in stmt

    def test_file_source_csv_creates_read_files_table(self, generator: UnityCatalogGenerator):
        """CSV file ReadNode should produce CREATE TABLE … USING DELTA AS SELECT … read_files(…, format => 'csv')."""
        node = ReadNode(
            node_id=1,
            file_path="/data/sales.csv",
            file_format="csv",
        )

        stmt = generator._read_node_ddl(node)

        assert stmt is not None
        assert "CREATE TABLE IF NOT EXISTS" in stmt
        assert "USING DELTA" in stmt
        assert "read_files(" in stmt
        assert "format => 'csv'" in stmt
        assert "'/data/sales.csv'" in stmt
        # Modern pattern — should NOT emit legacy EXTERNAL TABLE for CSV
        assert "CREATE EXTERNAL TABLE" not in stmt
        assert "USING CSV" not in stmt

    def test_file_source_parquet_creates_read_files_table(self, generator: UnityCatalogGenerator):
        """Parquet file ReadNode should ingest via read_files() into a Delta table."""
        node = ReadNode(
            node_id=1,
            file_path="/data/events.parquet",
            file_format="parquet",
        )

        stmt = generator._read_node_ddl(node)

        assert stmt is not None
        assert "USING DELTA" in stmt
        assert "read_files(" in stmt
        assert "format => 'parquet'" in stmt
        assert "USING PARQUET" not in stmt

    def test_file_source_yxdb_uses_delta(self, generator: UnityCatalogGenerator):
        """YXDB file (no direct equivalent) should produce DELTA table."""
        node = ReadNode(
            node_id=1,
            file_path="/data/data.yxdb",
            file_format="",
        )

        stmt = generator._read_node_ddl(node)

        assert stmt is not None
        assert "USING DELTA" in stmt
        assert "EXTERNAL" not in stmt

    def test_no_source_returns_none(self, generator: UnityCatalogGenerator):
        """ReadNode with no file_path and no connection should return None."""
        node = ReadNode(node_id=1)

        stmt = generator._read_node_ddl(node)

        assert stmt is None

    def test_default_connection_string(self, generator: UnityCatalogGenerator):
        """ReadNode with database source_type but no explicit connection string."""
        node = ReadNode(
            node_id=1,
            source_type="database",
            table_name="my_table",
        )

        stmt = generator._read_node_ddl(node)

        assert stmt is not None
        assert "default" in stmt  # conn_name falls back to "default"


class TestWriteNodeDDL:
    """Tests for DDL generation from WriteNode."""

    def test_write_node_creates_delta_table(self, generator: UnityCatalogGenerator):
        """WriteNode should produce CREATE TABLE with DELTA format."""
        node = WriteNode(
            node_id=1,
            connection_string="output_conn",
            table_name="results",
            file_path="/output/results.csv",
            write_mode="overwrite",
        )

        stmt = generator._write_node_ddl(node)

        assert stmt is not None
        assert "CREATE TABLE IF NOT EXISTS" in stmt
        assert "USING DELTA" in stmt
        assert "overwrite" in stmt

    def test_write_node_uses_table_name(self, generator: UnityCatalogGenerator):
        """WriteNode should use table_name for the table path."""
        node = WriteNode(
            node_id=1,
            connection_string="conn1",
            table_name="output_table",
        )

        stmt = generator._write_node_ddl(node)

        assert stmt is not None
        assert "output_table" in stmt

    def test_write_node_derives_name_from_path(self, generator: UnityCatalogGenerator):
        """WriteNode with no table_name should derive name from file_path."""
        node = WriteNode(
            node_id=1,
            file_path="/output/quarterly_report.csv",
        )

        stmt = generator._write_node_ddl(node)

        assert stmt is not None
        assert "quarterly_report" in stmt

    def test_write_mode_included(self, generator: UnityCatalogGenerator):
        """Write mode should appear in the DDL comment."""
        node = WriteNode(
            node_id=1,
            table_name="tbl",
            write_mode="append",
        )

        stmt = generator._write_node_ddl(node)

        assert "append" in stmt


class TestTableNameFromPath:
    """Tests for _table_name_from_path sanitization."""

    def test_simple_filename(self):
        result = UnityCatalogGenerator._table_name_from_path("/data/sales.csv", 1)
        assert result == "sales"

    def test_filename_with_special_chars(self):
        result = UnityCatalogGenerator._table_name_from_path("/data/my-file (2024).csv", 1)
        # Special chars replaced with underscores, then leading/trailing _ stripped
        assert result == "my_file__2024"

    def test_empty_path_uses_node_id(self):
        result = UnityCatalogGenerator._table_name_from_path("", 42)
        assert result == "table_42"

    def test_path_with_dots_in_dir(self):
        result = UnityCatalogGenerator._table_name_from_path("/data/v2.1/report.xlsx", 5)
        assert result == "report"

    def test_alphanumeric_preserved(self):
        result = UnityCatalogGenerator._table_name_from_path("/data/Sales2024.csv", 1)
        assert result == "Sales2024"

    def test_underscores_preserved(self):
        result = UnityCatalogGenerator._table_name_from_path("/data/my_table.csv", 1)
        assert result == "my_table"

    def test_all_special_chars_fallback(self):
        """If the stem becomes empty after sanitization, use node_id fallback."""
        result = UnityCatalogGenerator._table_name_from_path("/data/---.csv", 99)
        assert result == "table_99"


class TestGenerateDDLWithMockDAG:
    """Tests for the full generate_ddl method using a mock DAG."""

    def test_empty_dag_returns_empty_list(self, generator: UnityCatalogGenerator):
        dag = _make_dag_mock([])
        result = generator.generate_ddl(dag)
        assert result == []

    def test_single_read_node(self, generator: UnityCatalogGenerator):
        """A DAG with one database ReadNode should produce one DDL file."""
        node = ReadNode(
            node_id=1,
            source_type="database",
            connection_string="my_db",
            table_name="customers",
        )
        dag = _make_dag_mock([node])

        result = generator.generate_ddl(dag)

        assert len(result) == 1
        assert result[0].filename == "unity_catalog_ddl.sql"
        assert result[0].file_type == "sql"
        assert "CREATE TABLE IF NOT EXISTS" in result[0].content
        assert "Unity Catalog DDL generated by a2d" in result[0].content

    def test_multiple_io_nodes(self, generator: UnityCatalogGenerator):
        """Multiple IO nodes should produce multiple DDL statements in one file."""
        nodes = [
            ReadNode(node_id=1, source_type="database", table_name="input_tbl"),
            WriteNode(node_id=2, table_name="output_tbl"),
        ]
        dag = _make_dag_mock(nodes)

        result = generator.generate_ddl(dag)

        assert len(result) == 1
        content = result[0].content
        assert content.count("CREATE TABLE IF NOT EXISTS") == 2

    def test_non_io_nodes_ignored(self, generator: UnityCatalogGenerator):
        """Non-IO nodes (like FilterNode) should be skipped."""
        nodes = [
            ReadNode(node_id=1, source_type="database", table_name="tbl"),
            FilterNode(node_id=2, expression="[x] > 1"),
        ]
        dag = _make_dag_mock(nodes)

        result = generator.generate_ddl(dag)

        assert len(result) == 1
        content = result[0].content
        # Only one CREATE statement (for the ReadNode)
        assert content.count("CREATE TABLE IF NOT EXISTS") == 1

    def test_cloud_storage_node_ddl(self, generator: UnityCatalogGenerator):
        """CloudStorageNode (non-Delta) should ingest via read_files() into a Delta table."""
        node = CloudStorageNode(
            node_id=1,
            provider="s3",
            direction="input",
            bucket_or_container="my-bucket",
            path="data/sales.csv",
            file_format="csv",
        )
        dag = _make_dag_mock([node])

        result = generator.generate_ddl(dag)

        assert len(result) == 1
        content = result[0].content
        assert "CREATE TABLE IF NOT EXISTS" in content
        assert "USING DELTA" in content
        assert "read_files(" in content
        assert "format => 'csv'" in content
        assert "my-bucket/data/sales.csv" in content
        assert "CREATE EXTERNAL TABLE" not in content

    def test_dynamic_input_node_ddl(self, generator: UnityCatalogGenerator):
        """DynamicInputNode should produce a DELTA table."""
        node = DynamicInputNode(
            node_id=1,
            file_path_pattern="*.csv",
        )
        dag = _make_dag_mock([node])

        result = generator.generate_ddl(dag)

        assert len(result) == 1
        content = result[0].content
        assert "CREATE TABLE IF NOT EXISTS" in content
        assert "USING DELTA" in content
        assert "dynamic_input_1" in content

    def test_header_comments_present(self, generator: UnityCatalogGenerator):
        """Generated DDL should have header comments."""
        node = ReadNode(node_id=1, source_type="database", table_name="tbl")
        dag = _make_dag_mock([node])

        result = generator.generate_ddl(dag)

        content = result[0].content
        assert "Unity Catalog DDL generated by a2d" in content
        assert "Review and customize before executing" in content


class TestDDLFormatMap:
    """Tests for the _DDL_FORMAT_MAP constants."""

    def test_csv_maps_to_csv(self):
        assert _DDL_FORMAT_MAP["csv"] == "CSV"

    def test_parquet_maps_to_parquet(self):
        assert _DDL_FORMAT_MAP["parquet"] == "PARQUET"

    def test_json_maps_to_json(self):
        assert _DDL_FORMAT_MAP["json"] == "JSON"

    def test_empty_maps_to_delta(self):
        assert _DDL_FORMAT_MAP[""] == "DELTA"

    def test_yxdb_maps_to_parquet(self):
        assert _DDL_FORMAT_MAP["yxdb"] == "PARQUET"

    def test_xlsx_maps_to_csv(self):
        assert _DDL_FORMAT_MAP["xlsx"] == "CSV"
