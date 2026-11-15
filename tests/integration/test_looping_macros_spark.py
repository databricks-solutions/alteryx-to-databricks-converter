"""Run the code generated for real batch and iterative macros on Spark and
compare with what Alteryx outputs.

Local Spark needs a JVM; set A2D_SPARK_PROFILE to a Databricks CLI profile to
run on serverless through Databricks Connect instead. Skipped when neither works.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path

import pytest

from a2d.config import ConversionConfig, OutputFormat
from a2d.pipeline import ConversionPipeline
from a2d.verification.spark_backend import spark_available

FIXTURES = Path(__file__).parents[1] / "fixtures" / "looping_macros" / "advanced_ch1"
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

    session = SparkSession.builder.master("local[1]").appName("a2d-looping-macros").getOrCreate()
    yield session
    session.stop()


def _cell(name: str, node_id: int) -> str:
    path = FIXTURES / name
    result = ConversionPipeline(
        ConversionConfig(input_path=path, output_format=OutputFormat.PYSPARK, expand_macros=True)
    ).convert(path)
    nb = result.output.files[0]
    cells = nb.content.split("\n\n# COMMAND ----------\n\n")
    return next(c for c, nid in zip(cells, result.output.cell_nodes[nb.filename], strict=True) if nid == node_id)


def _run(spark, code: str, **frames) -> dict:
    from pyspark.sql import functions as F  # noqa: N812

    env = {"spark": spark, "F": F, "functools": functools, **frames}
    exec(code, env)  # generated code under test
    return env


def test_batch_macro_runs_once_per_group(spark):
    # The macro keeps a group's rows whose share of the group's total is <= 10
    # and whose field4 is type1; each run sees only its group's rows.
    data = spark.createDataFrame(
        [("a", "c", 10, "type1"), ("a", "d", 20, "type1"), ("b", "c", 5, "type1"), ("b", "d", 50, "type2")],
        "field1 string, field2 string, field3 int, field4 string",
    )
    env = _run(spark, _cell("Batch Macros (Group By).yxmd", 9), df_1=data, df_2=data.select("field1").distinct())
    rows = sorted((r.field1, r.field2, r.sum_field3, r.calculation) for r in env["df_9"].collect())
    # Group a: total 30 -> 3.0 and 1.5 pass. Group b: total 55 -> 11.0 (too big) and type2.
    assert rows == [("a", "c", 30, 3.0), ("a", "d", 30, 1.5)]


def test_iterative_macro_stops_when_nothing_is_left_to_iterate(spark):
    # Doubles initial_value each pass; a record leaves on "final" once iteration >= 10.
    env = _run(spark, _cell("Iterative Macros.yxmd", 27), df_3=spark.createDataFrame([(10,)], "initial_value bigint"))
    assert [tuple(r) for r in env["df_27_final"].collect()] == [(10 * 2**10, 10)]
    assert env["df_27_iterate"].count() == 0


def test_iterative_macro_errors_at_its_limit_like_alteryx(spark):
    code = _cell("Iterative Macros.yxmd", 27).replace("range(100)", "range(3)")
    with pytest.raises(RuntimeError, match="limit"):
        _run(spark, code, df_3=spark.createDataFrame([(10,)], "initial_value bigint"))
