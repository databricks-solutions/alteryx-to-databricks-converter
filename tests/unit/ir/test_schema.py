"""Columns between tools: kept from the file's <MetaInfo>, derived where a tool's
effect on columns is known, unknown otherwise."""

from __future__ import annotations

from lxml import etree

from a2d.config import ConversionConfig
from a2d.converters import ConverterRegistry
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    AppendFieldsNode,
    FieldOperation,
    FilterNode,
    FormulaField,
    FormulaNode,
    JoinKey,
    JoinNode,
    ReadNode,
    SelectNode,
    SummarizeNode,
    UnsupportedNode,
)
from a2d.ir.schema import describe, input_columns, output_columns
from a2d.parser.node_parser import NodeParser

NODE_XML = """
<Node ToolID="7">
  <GuiSettings Plugin="AlteryxBasePluginsGui.Filter.Filter"><Position x="1" y="2"/></GuiSettings>
  <Properties>
    <Configuration><Mode>Custom</Mode><Expression>[a] &gt; 1</Expression></Configuration>
    <MetaInfo connection="True"><RecordInfo><Field name="a" type="Int64"/><Field name="b" type="V_String"/></RecordInfo></MetaInfo>
    <MetaInfo connection="False"><RecordInfo><Field name="a" type="Int64"/><Field name="b" type="V_String"/></RecordInfo></MetaInfo>
  </Properties>
</Node>
"""


def test_parser_and_converter_keep_saved_columns():
    parsed = NodeParser().parse(etree.fromstring(NODE_XML))
    assert parsed.output_fields == {
        "True": [("a", "Int64"), ("b", "V_String")],
        "False": [("a", "Int64"), ("b", "V_String")],
    }
    node = ConverterRegistry.convert_node(parsed, ConversionConfig())
    assert node.output_fields["True"] == [("a", "Int64"), ("b", "V_String")]


def test_metainfo_without_connection_is_the_output():
    xml = NODE_XML.replace(' connection="True"', "").split('<MetaInfo connection="False">')[0] + "</Properties></Node>"
    assert NodeParser().parse(etree.fromstring(xml)).output_fields == {"Output": [("a", "Int64"), ("b", "V_String")]}


def _dag(*nodes, edges=()):
    dag = WorkflowDAG()
    for n in nodes:
        dag.add_node(n)
    for e in edges:
        dag.add_edge(*e)
    return dag


READ = ReadNode(node_id=1, output_fields={"Output": [("a", "Int64"), ("b", "String")]})


def test_filter_and_formula_and_select_derive_columns():
    dag = _dag(
        READ,
        FilterNode(node_id=2),
        FormulaNode(node_id=3, formulas=[FormulaField("c", "[a]*2", "Double"), FormulaField("a", "[a]+1")]),
        SelectNode(
            node_id=4, field_operations=[FieldOperation("b", selected=False), FieldOperation("c", rename_to="c2")]
        ),
        edges=[(1, 2, "Output", "Input"), (2, 3, "True", "Input"), (3, 4)],
    )
    assert output_columns(dag, 2, "True") == [("a", "Int64"), ("b", "String")]
    assert output_columns(dag, 3) == [("a", "Int64"), ("b", "String"), ("c", "Double")]
    assert output_columns(dag, 4) == [("a", "Int64"), ("c2", "Double")]


def test_join_output_uses_alteryx_right_prefix_and_select():
    left = ReadNode(node_id=1, output_fields={"Output": [("K", "Int64"), ("A", "String")]})
    right = ReadNode(node_id=2, output_fields={"Output": [("K", "Int64"), ("B", "String")]})
    join = JoinNode(node_id=3, join_keys=[JoinKey("K", "K")], select_right=[FieldOperation("Right_K", selected=False)])
    dag = _dag(left, right, join, edges=[(1, 3, "Output", "Left"), (2, 3, "Output", "Right")])
    assert output_columns(dag, 3, "Join") == [("K", "Int64"), ("A", "String"), ("B", "String")]
    assert output_columns(dag, 3, "Left") == [("K", "Int64"), ("A", "String")]


def test_unknown_stays_unknown():
    dag = _dag(
        READ,
        UnsupportedNode(node_id=2, original_tool_type="DynamicSelect"),
        SummarizeNode(node_id=3),
        edges=[(1, 2), (2, 3)],
    )
    assert output_columns(dag, 2) is None
    assert input_columns(dag, 2) == {"Input": [("a", "Int64"), ("b", "String")]}
    assert describe(output_columns(dag, 2)) == "not known"


def test_append_fields_name_clash_is_not_guessed():
    target = ReadNode(node_id=1, output_fields={"Output": [("a", "")]})
    source = ReadNode(node_id=2, output_fields={"Output": [("a", "")]})
    dag = _dag(
        target, source, AppendFieldsNode(node_id=3), edges=[(1, 3, "Output", "Targets"), (2, 3, "Output", "Source")]
    )
    assert output_columns(dag, 3) is None
