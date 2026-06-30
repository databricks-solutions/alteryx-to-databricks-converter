"""Tests for the DataverseInput converter."""

from __future__ import annotations

from a2d.converters import ConverterRegistry
from a2d.ir.nodes import ReadNode

from .conftest import DEFAULT_CONFIG, make_node


class TestDataverseInputConverter:
    def test_basic_dataverse_input(self):
        node = make_node(
            tool_type="DataverseInput",
            plugin_name="DataverseInput_1_2_1",
            configuration={
                "ConnectionId": "abc-123",
                "InstanceUrl": "https://example.crm.dynamics.com",
                "LogicalName": "pq_tbl_instrument",
                "LogicalCollectionName": "pq_tbl_instruments",
                "Query": "",
                "MaxNumberOfRows": "50",
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, ReadNode)
        assert result.source_type == "dataverse"
        assert result.table_name == "pq_tbl_instrument"
        assert result.file_format == "dataverse"
        assert result.record_limit == 50
        assert "abc-123" in result.connection_string
        assert any("Dataverse" in n for n in result.conversion_notes)

    def test_dataverse_falls_back_to_collection_name(self):
        node = make_node(
            tool_type="DataverseInput",
            plugin_name="DataverseInput_1_2_1",
            configuration={
                "LogicalName": "",
                "LogicalCollectionName": "pq_tbl_things",
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, ReadNode)
        assert result.table_name == "pq_tbl_things"

    def test_dataverse_invalid_max_rows_ignored(self):
        node = make_node(
            tool_type="DataverseInput",
            plugin_name="DataverseInput_1_2_1",
            configuration={
                "LogicalName": "tbl",
                "MaxNumberOfRows": "not-a-number",
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert result.record_limit is None

    def test_dataverse_query_preserved_in_notes(self):
        node = make_node(
            tool_type="DataverseInput",
            plugin_name="DataverseInput_1_2_1",
            configuration={
                "LogicalName": "tbl",
                "CustomODataQuery": "$filter=Status eq 'Active'",
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert result.query == "$filter=Status eq 'Active'"
        assert any("$filter" in n for n in result.conversion_notes)
