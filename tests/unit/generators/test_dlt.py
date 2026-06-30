"""Tests for the Delta Live Tables code generator."""

from __future__ import annotations

import pytest

from a2d.config import ConversionConfig
from a2d.generators.dlt import DLTGenerator
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    AggAction,
    AggregationField,
    FilterNode,
    JoinKey,
    JoinNode,
    ReadNode,
    SummarizeNode,
    UnsupportedNode,
)


@pytest.fixture
def config() -> ConversionConfig:
    return ConversionConfig()


@pytest.fixture
def generator(config: ConversionConfig) -> DLTGenerator:
    return DLTGenerator(config)


class TestDLTReadNode:
    def test_read_node_generates_dlt_table(self, generator: DLTGenerator):
        """ReadNode should produce a @dlt.table function with spark.read."""
        node = ReadNode(
            node_id=1,
            original_tool_type="Input Data",
            file_path="/data/input.csv",
            file_format="csv",
            has_header=True,
        )
        dag = WorkflowDAG()
        dag.add_node(node)

        output = generator.generate(dag, "test_dlt")
        content = output.files[0].content

        assert "@dlt.table" in content
        assert "def step_1_input_data():" in content
        assert 'spark.read.format("csv")' in content
        assert '"/data/input.csv"' in content
        assert output.files[0].filename == "test_dlt_dlt.py"


class TestDLTFilterNode:
    def test_filter_produces_dlt_function(self, generator: DLTGenerator):
        """FilterNode should produce a @dlt.table that reads from upstream and filters."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        filt = FilterNode(node_id=2, original_tool_type="Filter", expression="[Age] > 25")

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(filt)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content

        assert "dlt.read(" in content
        assert ".filter(" in content
        assert "@dlt.table" in content


class TestDLTJoinNode:
    def test_join_produces_dlt_function(self, generator: DLTGenerator):
        """JoinNode produces a DLT function reading from two upstream tables."""
        left = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/left.csv", file_format="csv")
        right = ReadNode(node_id=2, original_tool_type="Input Data", file_path="/right.csv", file_format="csv")
        join = JoinNode(
            node_id=3,
            original_tool_type="Join",
            join_keys=[JoinKey(left_field="id", right_field="id")],
            join_type="inner",
        )

        dag = WorkflowDAG()
        dag.add_node(left)
        dag.add_node(right)
        dag.add_node(join)
        dag.add_edge(1, 3, destination_anchor="Left")
        dag.add_edge(2, 3, destination_anchor="Right")

        output = generator.generate(dag)
        content = output.files[0].content

        assert "dlt.read(" in content
        assert ".join(" in content
        assert '"inner"' in content


class TestDLTSummarizeNode:
    def test_summarize_produces_groupby(self, generator: DLTGenerator):
        """SummarizeNode produces a DLT function with groupBy and agg."""
        read = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        summ = SummarizeNode(
            node_id=2,
            original_tool_type="Summarize",
            aggregations=[
                AggregationField(field_name="Dept", action=AggAction.GROUP_BY),
                AggregationField(field_name="Salary", action=AggAction.SUM, output_field_name="Total"),
            ],
        )

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(summ)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content

        assert "groupBy(" in content
        assert "F.sum" in content
        assert '"Total"' in content


class TestDLTFormat:
    def test_dlt_file_header(self, generator: DLTGenerator):
        """DLT output should have import dlt and proper structure."""
        node = ReadNode(node_id=1, original_tool_type="Input Data", file_path="/data.csv", file_format="csv")
        dag = WorkflowDAG()
        dag.add_node(node)

        output = generator.generate(dag, "my_pipeline")
        content = output.files[0].content

        assert "import dlt" in content
        assert "from pyspark.sql import functions as F" in content
        assert "Databricks notebook source" in content
        assert "my_pipeline" in content
        assert output.files[0].file_type == "python"


class TestDLTUnsupported:
    def test_unsupported_node_passthrough(self, generator: DLTGenerator):
        """UnsupportedNode should produce a passthrough with warning."""
        read = ReadNode(node_id=1, original_tool_type="Input", file_path="/data.csv", file_format="csv")
        unsup = UnsupportedNode(
            node_id=2,
            original_tool_type="SpatialMatch",
            unsupported_reason="Geospatial not supported",
        )

        dag = WorkflowDAG()
        dag.add_node(read)
        dag.add_node(unsup)
        dag.add_edge(1, 2)

        output = generator.generate(dag)
        content = output.files[0].content

        assert "UNSUPPORTED" in content
        assert "passthrough" in content
        assert len(output.warnings) >= 1
