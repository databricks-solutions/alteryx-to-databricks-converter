"""Run the code generated for Alteryx's Join Multiple on Spark and compare with
what Alteryx outputs (help: Join Multiple tool).

Local Spark needs a JVM; set A2D_SPARK_PROFILE to a Databricks CLI profile to run
on serverless through Databricks Connect. Skipped when neither works.
"""

from __future__ import annotations

import os

import pytest

from a2d.generators.join_multiple_code import python_lines, sql_body
from a2d.ir.nodes import JoinMultipleNode
from a2d.verification.spark_backend import spark_available

_PROFILE = os.environ.get("A2D_SPARK_PROFILE")
_ok, _why = (True, "") if _PROFILE else spark_available()
pytestmark = pytest.mark.skipif(not _ok, reason=f"Spark not available: {_why}")


@pytest.fixture(scope="module")
def spark():
    if _PROFILE:
        from databricks.connect import DatabricksSession

        yield DatabricksSession.builder.profile(_PROFILE).serverless(True).getOrCreate()
        return
    from pyspark.sql import SparkSession

    session = SparkSession.builder.master("local[1]").appName("a2d-join-multiple").getOrCreate()
    yield session
    session.stop()


def _python(spark, node, frames):
    from pyspark.sql import Window
    from pyspark.sql import functions as F  # noqa: N812

    env = {"F": F, "Window": Window, **{f"in{i}": df for i, df in enumerate(frames, start=1)}}
    exec("\n".join(python_lines(node, [f"in{i}" for i in range(1, len(frames) + 1)], "OUT", repr)), env)
    return env["OUT"]


def _sql(spark, node, frames):
    names = []
    for i, df in enumerate(frames, start=1):
        df.createOrReplaceTempView(f"a2d_jm_in{i}")
        names.append(f"a2d_jm_in{i}")
    body, _ = sql_body(node, names, None)
    return spark.sql(body)


def _frames(spark, *sizes):
    return [
        spark.createDataFrame([(f"in{i}-{r}",) for r in range(1, n + 1)], f"v{i} string")
        for i, n in enumerate(sizes, 1)
    ]


@pytest.mark.parametrize("run", [_python, _sql], ids=["pyspark", "sql"])
def test_by_position_keeps_all_records(spark, run):
    # 3, 5 and 7 records -> 7 rows, with nulls where an input ran out.
    node = JoinMultipleNode(node_id=1, by_position=True, join_type="full")
    rows = run(spark, node, _frames(spark, 3, 5, 7)).collect()
    assert len(rows) == 7
    got = {(r.v1, r.v2, r.v3) for r in rows}
    assert ("in1-1", "in2-1", "in3-1") in got and ("in1-3", "in2-3", "in3-3") in got
    assert (None, "in2-4", "in3-4") in got and (None, None, "in3-7") in got


@pytest.mark.parametrize("run", [_python, _sql], ids=["pyspark", "sql"])
def test_by_position_only_records_that_join(spark, run):
    node = JoinMultipleNode(node_id=1, by_position=True, join_type="inner")
    assert run(spark, node, _frames(spark, 3, 5, 7)).count() == 3


def test_keys_and_names_like_alteryx(spark):
    a = spark.createDataFrame([(1, "a1"), (2, "a2")], "Id int, Name string")
    b = spark.createDataFrame([(1, "b1"), (3, "b3")], "Key int, Name string")
    c = spark.createDataFrame([(3, "c3")], "Id int, Name string")
    node = JoinMultipleNode(node_id=1, keys_by_input={1: ["Id"], 2: ["Key"], 3: ["Id"]}, join_type="full")
    out = _python(spark, node, [a, b, c])
    assert out.columns == ["Id", "Name", "Key", "Input_#2_Name", "Input_#3_Id", "Input_#3_Name"]
    rows = {tuple(r) for r in out.collect()}
    # Record 3 is only in #2 and #3: it still joins, through the shared hidden key.
    assert rows == {(1, "a1", 1, "b1", None, None), (2, "a2", None, None, None, None), (None, None, 3, "b3", 3, "c3")}


def test_the_select_list_renames_and_drops(spark):
    a = spark.createDataFrame([(1, "a1")], "Id int, Name string")
    b = spark.createDataFrame([(1, "b1")], "Id int, Name string")
    node = JoinMultipleNode(
        node_id=1,
        keys_by_input={1: ["Id"], 2: ["Id"]},
        join_type="inner",
        select_fields=[("Input_#2_Id", False, None), ("Input_#2_Name", True, "OtherName")],
    )
    out = _python(spark, node, [a, b])
    assert out.columns == ["Id", "Name", "OtherName"]
    node.keep_unlisted = False
    assert _python(spark, node, [a, b]).columns == ["OtherName"]
