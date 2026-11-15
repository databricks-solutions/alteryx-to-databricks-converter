"""Join Multiple as Designer saves it, and inputs taken in their numbered order.

Real files (Packt: CH04-R04 Arranging Data, the Server Usage Report's Connector
macro) save one JoinInfo per input with its key fields, or join by record
position, and number each connection ("#1", "#2", ...). The converter used to
read neither, and the SQL and DLT outputs kept only one of several inputs that
arrive on the same anchor, for Union too.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from lxml import etree

from a2d.config import ConversionConfig, OutputFormat
from a2d.converters import ConverterRegistry
from a2d.generators.pyspark import PySparkGenerator
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import JoinMultipleNode, ReadNode, UnionNode
from a2d.parser.connection_parser import ConnectionParser
from a2d.pipeline import ConversionPipeline
from tests.unit.converters.conftest import DEFAULT_CONFIG, make_node

PACKT = Path(__file__).parents[2] / "fixtures" / "packt"


def test_the_connection_number_is_kept():
    conn = etree.fromstring(
        '<Connection name="#2"><Origin ToolID="21" Connection="Output"/><Destination ToolID="22" Connection="Input"/></Connection>'
    )
    assert ConnectionParser().parse(conn).name == "#2"


class TestConverter:
    def test_keys_per_input(self):
        cfg = {
            "JoinByRecPos": {"@value": "False"},
            "JoinFields": {
                "JoinInfo": [
                    {"@connection": "#1", "Field": {"@field": "CollectionId"}},
                    {"@connection": "#2", "Field": [{"@field": "Id"}, {"@field": "Day"}]},
                ]
            },
            "OutputJoinOnly": {"@value": "False"},
            "SelectConfiguration": {
                "Configuration": {
                    "SelectFields": {
                        "SelectField": [
                            {"@field": "Input_#2_Id", "@selected": "False"},
                            {"@field": "Input_#2_Name", "@selected": "True", "@rename": "Other"},
                            {"@field": "*Unknown", "@selected": "False"},
                        ]
                    }
                }
            },
        }
        node = ConverterRegistry.convert_node(make_node(tool_type="JoinMultiple", configuration=cfg), DEFAULT_CONFIG)
        assert isinstance(node, JoinMultipleNode)
        assert node.keys_by_input == {1: ["CollectionId"], 2: ["Id", "Day"]}
        assert (node.by_position, node.join_type, node.keep_unlisted) == (False, "full", False)
        assert node.select_fields == [("Input_#2_Id", False, None), ("Input_#2_Name", True, "Other")]
        assert "same number of key fields" in " ".join(node.conversion_notes)

    def test_by_position_only_records_that_join(self):
        cfg = {"JoinByRecPos": {"@value": "True"}, "OutputJoinOnly": {"@value": "True"}}
        node = ConverterRegistry.convert_node(make_node(tool_type="JoinMultiple", configuration=cfg), DEFAULT_CONFIG)
        assert (node.by_position, node.join_type) == (True, "inner")


def _union_dag(reverse: bool) -> WorkflowDAG:
    dag = WorkflowDAG()
    for i in (1, 2, 3):
        dag.add_node(ReadNode(node_id=i, original_tool_type="Input", file_path=f"/{i}.csv", file_format="csv"))
    dag.add_node(UnionNode(node_id=9, original_tool_type="Union"))
    order = [3, 2, 1] if reverse else [1, 2, 3]
    for i in order:
        dag.add_edge(i, 9, "Output", "Input", input_name=f"#{i}")
    return dag


@pytest.mark.parametrize("reverse", [False, True])
def test_union_inputs_come_in_their_numbered_order(reverse):
    code = PySparkGenerator(ConversionConfig()).generate(_union_dag(reverse)).files[0].content
    assert "df_9 = df_1.unionByName(df_2, allowMissingColumns=True).unionByName(df_3, allowMissingColumns=True)" in code


@pytest.mark.parametrize("fmt", [OutputFormat.SQL, OutputFormat.DLT, OutputFormat.LAKEFLOW], ids=lambda f: f.value)
def test_sql_and_pipelines_keep_every_union_input(fmt):
    # A real 3-input Union: the SQL and DLT outputs used to keep only the last input.
    logging.disable(logging.WARNING)
    path = PACKT / "CH01-R06-Handling_different_number_format_from_TEXT_files.yxmd"
    result = ConversionPipeline(ConversionConfig(input_path=path, output_format=fmt)).convert(path)
    logging.disable(logging.NOTSET)
    text = "\n".join(f.content for f in result.output.files)
    for source in ("step_10_", "step_11_", "step_15_"):
        assert text.count(source) >= 2, source  # defined, and read by the union


def test_join_multiple_by_position_on_a_real_workflow():
    logging.disable(logging.WARNING)
    path = PACKT / "CH04-R04-Arranging_Data.yxmd"
    result = ConversionPipeline(ConversionConfig(input_path=path, output_format=OutputFormat.PYSPARK)).convert(path)
    logging.disable(logging.NOTSET)
    code = result.output.files[0].content
    assert "zip([df_20, df_21, df_24, df_27], None or [None] * 4)" in code  # inputs #1..#4, by position
    assert "how='full'" in code
