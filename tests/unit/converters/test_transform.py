"""Tests for transform converters."""

from __future__ import annotations

from a2d.converters import ConverterRegistry
from a2d.ir.nodes import (
    AggAction,
    CountRecordsNode,
    CrossTabNode,
    RunningTotalNode,
    SummarizeNode,
    TransposeNode,
)

from .conftest import DEFAULT_CONFIG, make_node


class TestSummarizeConverter:
    def test_summarize_group_by_sum(self):
        node = make_node(
            tool_type="Summarize",
            configuration={
                "SummarizeFields": {
                    "SummarizeField": [
                        {"@field": "Region", "@action": "GroupBy"},
                        {"@field": "Revenue", "@action": "Sum", "@rename": "TotalRevenue"},
                        {"@field": "OrderID", "@action": "Count"},
                    ]
                }
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, SummarizeNode)
        assert len(result.aggregations) == 3
        assert result.aggregations[0].field_name == "Region"
        assert result.aggregations[0].action == AggAction.GROUP_BY
        assert result.aggregations[1].field_name == "Revenue"
        assert result.aggregations[1].action == AggAction.SUM
        assert result.aggregations[1].output_field_name == "TotalRevenue"
        assert result.aggregations[2].action == AggAction.COUNT


class TestCrossTabConverter:
    def test_cross_tab(self):
        node = make_node(
            tool_type="CrossTab",
            configuration={
                "GroupFields": {"Field": [{"@field": "Region"}]},
                "HeaderField": "Product",
                "ValueField": "Sales",
                "Aggregation": "Sum",
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, CrossTabNode)
        assert result.group_fields == ["Region"]
        assert result.header_field == "Product"
        assert result.value_field == "Sales"
        assert result.aggregation == "Sum"


class TestTransposeConverter:
    def test_transpose(self):
        node = make_node(
            tool_type="Transpose",
            configuration={
                "KeyFields": {"Field": [{"@field": "ID"}]},
                "DataFields": {
                    "Field": [
                        {"@field": "Jan"},
                        {"@field": "Feb"},
                        {"@field": "Mar"},
                    ]
                },
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, TransposeNode)
        assert result.key_fields == ["ID"]
        assert result.data_fields == ["Jan", "Feb", "Mar"]


class TestRunningTotalConverter:
    def test_running_total(self):
        node = make_node(
            tool_type="RunningTotal",
            configuration={
                "RunningFields": {
                    "RunningField": [
                        {"@field": "Sales", "@type": "Sum", "@rename": "CumSales"},
                    ]
                },
                "GroupFields": {"Field": [{"@field": "Region"}]},
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, RunningTotalNode)
        assert len(result.running_fields) == 1
        assert result.running_fields[0].field_name == "Sales"
        assert result.running_fields[0].running_type == "Sum"
        assert result.running_fields[0].output_field_name == "CumSales"
        assert result.group_fields == ["Region"]


class TestCountRecordsConverter:
    def test_count_records(self):
        node = make_node(
            tool_type="CountRecords",
            configuration={"FieldName": "TotalRows"},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, CountRecordsNode)
        assert result.output_field == "TotalRows"
