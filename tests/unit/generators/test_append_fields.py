"""Append Fields appends every Source record to every Targets record, like Alteryx.

The tool's CartesianMode only decides what happens with more than 16 Source
records: stop (Error), carry on with a warning (Warn) or carry on (Allow). The
generated code used to keep one Source record (``.limit(1)``), silently dropping
the rest.
"""

from __future__ import annotations

import pytest

from a2d.config import ConversionConfig
from a2d.generators.dlt import DLTGenerator
from a2d.generators.pyspark import PySparkGenerator
from a2d.generators.sql import SQLGenerator
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import AppendFieldsNode, ReadNode


def _dag(mode: str) -> WorkflowDAG:
    dag = WorkflowDAG()
    dag.add_node(ReadNode(node_id=1, original_tool_type="Input", file_path="/t.csv", file_format="csv"))
    dag.add_node(ReadNode(node_id=2, original_tool_type="Input", file_path="/s.csv", file_format="csv"))
    dag.add_node(AppendFieldsNode(node_id=3, original_tool_type="AppendFields", cartesian_mode=mode))
    dag.add_edge(1, 3, "Output", "Targets")
    dag.add_edge(2, 3, "Output", "Source")
    return dag


def _code(gen, mode: str) -> str:
    return "\n".join(f.content for f in gen(ConversionConfig()).generate(_dag(mode)).files)


@pytest.mark.parametrize("mode", ["error", "warn", "allow"])
def test_pyspark_keeps_every_source_record(mode):
    code = _code(PySparkGenerator, mode)
    assert "df_3 = df_1.crossJoin(F.broadcast(df_2))" in code
    assert ".limit(1)" not in code


def test_pyspark_stops_on_more_than_16_source_records_when_set_to():
    code = _code(PySparkGenerator, "error")
    assert "if df_2.limit(17).count() > 16:" in code and "raise ValueError" in code
    assert "print('WARNING" in _code(PySparkGenerator, "warn")
    assert "count() > 16" not in _code(PySparkGenerator, "allow")


@pytest.mark.parametrize("gen", [SQLGenerator, DLTGenerator], ids=["sql", "dlt"])
def test_sql_and_dlt_read_the_targets_anchor(gen):
    # Designer names the anchor "Targets"; reading "Target" left the join unwired.
    code = _code(gen, "allow")
    assert "not connected" not in code and "MISSING" not in code
