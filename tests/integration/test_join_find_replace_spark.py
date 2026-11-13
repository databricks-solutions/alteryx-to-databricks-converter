"""Run the code generated for Alteryx Join and Find Replace on Spark and compare
with what Alteryx outputs. Skipped where Spark can't start (no JVM)."""

from __future__ import annotations

import pytest

from a2d.generators.find_replace_code import find_replace_lines
from a2d.generators.join_code import join_output_lines
from a2d.generators.sql import _find_replace_sql, _join_select_list
from a2d.ir.nodes import FieldAction, FieldOperation, FindReplaceNode, JoinKey, JoinNode
from a2d.verification.spark_backend import spark_available

_ok, _why = spark_available()
pytestmark = pytest.mark.skipif(not _ok, reason=f"Spark not available: {_why}")


@pytest.fixture(scope="module")
def spark():
    from pyspark.sql import SparkSession

    session = SparkSession.builder.master("local[1]").appName("a2d-join-fr").getOrCreate()
    yield session
    session.stop()


def _op(name, selected=True, rename=None):
    action = FieldAction.RENAME if rename else (FieldAction.SELECT if selected else FieldAction.DESELECT)
    return FieldOperation(field_name=name, selected=selected, rename_to=rename, action=action)


def _run(code: str, **frames):
    from pyspark.sql import functions as F  # noqa: N812

    env = {"F": F, **frames}
    exec(code, env)  # generated code under test
    return env["OUT"]


def _rows(df):
    return sorted(tuple(r) for r in df.collect())


KEYS = [JoinKey("COMPANY_ID", "COMPANY_ID"), JoinKey("ARTICLE_ID", "ARTICLE_ID")]


@pytest.fixture(scope="module")
def sides(spark):
    left = spark.createDataFrame(
        [(1, "a1", "x"), (1, "a2", "y"), (2, "a1", "z")], "COMPANY_ID int, ARTICLE_ID string, A string"
    )
    right = spark.createDataFrame(
        [(1, "a1", "b1", "ra"), (2, "a1", "b2", "rb"), (3, "a9", "b3", "rc")],
        "COMPANY_ID int, ARTICLE_ID string, B string, A string",
    )
    return left, right


def test_join_names_like_alteryx(sides):
    left, right = sides
    node = JoinNode(
        node_id=25, join_keys=KEYS, select_right=[_op("Right_COMPANY_ID", False), _op("Right_ARTICLE_ID", False)]
    )
    out = _run("\n".join(join_output_lines(node, "L", "R", "OUT")), L=left, R=right)
    assert out.columns == ["COMPANY_ID", "ARTICLE_ID", "A", "B", "Right_A"]
    assert _rows(out) == [(1, "a1", "x", "b1", "ra"), (2, "a1", "z", "b2", "rb")]
    out.select("A", "Right_A").collect()  # later steps can read both without ambiguity


def test_join_only_listed_fields(sides):
    left, right = sides
    node = JoinNode(
        node_id=26,
        join_keys=KEYS,
        keep_unlisted=False,
        select_left=[_op("COMPANY_ID"), _op("A", True, "A_left")],
        select_right=[_op("B"), _op("Right_A", True, "A_right")],
    )
    out = _run("\n".join(join_output_lines(node, "L", "R", "OUT")), L=left, R=right)
    assert sorted(out.columns) == ["A_left", "A_right", "B", "COMPANY_ID"]


def test_sql_join_matches_pyspark(spark, sides):
    left, right = sides
    right_keys_only = right.drop("A")  # SQL can't rename shared columns it doesn't know about
    node = JoinNode(
        node_id=25, join_keys=KEYS, select_right=[_op("Right_COMPANY_ID", False), _op("Right_ARTICLE_ID", False)]
    )
    expected = _run("\n".join(join_output_lines(node, "L", "R", "OUT")), L=left, R=right_keys_only)
    left.createOrReplaceTempView("L")
    right_keys_only.createOrReplaceTempView("R")
    on = " AND ".join(f"l.`{k.left_field}` = r.`{k.right_field}`" for k in KEYS)
    got = spark.sql(f"SELECT {_join_select_list(node)} FROM L l INNER JOIN R r ON {on}")
    assert sorted(got.columns) == sorted(expected.columns)
    assert _rows(got.select(*expected.columns)) == _rows(expected)


def test_sql_join_with_known_columns_matches_pyspark(spark, sides):
    """With both inputs' columns known (saved by Designer), SQL names every shared
    column like Alteryx, including the non-key A."""
    left, right = sides
    node = JoinNode(
        node_id=25, join_keys=KEYS, select_right=[_op("Right_COMPANY_ID", False), _op("Right_ARTICLE_ID", False)]
    )
    expected = _run("\n".join(join_output_lines(node, "L", "R", "OUT")), L=left, R=right)
    left.createOrReplaceTempView("L")
    right.createOrReplaceTempView("R")
    cols = lambda df: [(f.name, "") for f in df.schema.fields]  # noqa: E731
    on = " AND ".join(f"l.`{k.left_field}` = r.`{k.right_field}`" for k in KEYS)
    got = spark.sql(f"SELECT {_join_select_list(node, cols(left), cols(right))} FROM L l INNER JOIN R r ON {on}")
    assert sorted(got.columns) == sorted(expected.columns) == sorted(["COMPANY_ID", "ARTICLE_ID", "A", "B", "Right_A"])
    assert _rows(got.select(*expected.columns)) == _rows(expected)


@pytest.fixture(scope="module")
def cities(spark):
    target = spark.createDataFrame([("NYC",), ("nyc",), ("LA",), (None,)], "city string")
    lookup = spark.createDataFrame(
        [("nyc", "New York", "East"), ("la", "Los Angeles", "West")], "code string, name string, region string"
    )
    return target, lookup


def _fr(**kw):
    return FindReplaceNode(
        **{"node_id": 31, "find_field": "city", "search_field": "code", "replace_field": "name", **kw}
    )


def test_find_replace_entire_field_case_insensitive(spark, cities):
    target, lookup = cities
    node = _fr(case_sensitive=False)
    out = _run("\n".join(find_replace_lines(node, "T", "LK", "OUT")), T=target, LK=lookup)
    want = sorted([("New York",), ("New York",), ("Los Angeles",), ("<null>",)])
    assert out.columns == ["city"]
    assert _rows(out.fillna("<null>")) == want
    target.createOrReplaceTempView("T")
    lookup.createOrReplaceTempView("LK")
    assert _rows(spark.sql(_find_replace_sql(node, {"Targets": "T", "Source": "LK"}, [])).fillna("<null>")) == want


def test_find_replace_entire_field_append(spark, cities):
    target, lookup = cities
    node = _fr(replace_mode="append", append_fields=["name", "region"])
    want = sorted([("NYC", "-", "-"), ("nyc", "New York", "East"), ("LA", "-", "-"), ("-", "-", "-")])
    out = _run("\n".join(find_replace_lines(node, "T", "LK", "OUT")), T=target, LK=lookup)
    assert _rows(out.fillna("-")) == want
    target.createOrReplaceTempView("T")
    lookup.createOrReplaceTempView("LK")
    sql = _find_replace_sql(node, {"Targets": "T", "Source": "LK"}, [])
    assert _rows(spark.sql(sql).select("city", "name", "region").fillna("-")) == want


def test_find_replace_any_part_append_numeric_lookup(spark):
    target = spark.createDataFrame([("order 123 shipped",), ("no ref",), ("4567",)], "ref string")
    lookup = spark.createDataFrame([(123, "first"), (12, "second"), (4567, "third")], "id int, label string")
    node = FindReplaceNode(
        node_id=33,
        find_field="ref",
        search_field="id",
        find_mode="contains",
        replace_mode="append",
        append_fields=["label"],
    )
    out = _run("\n".join(find_replace_lines(node, "T", "LK", "OUT")), T=target, LK=lookup)
    got = {r["ref"]: r["label"] for r in out.collect()}
    assert out.count() == 3  # one row per F row
    assert got["no ref"] is None and got["4567"] == "third"


def test_find_replace_any_part_every_item_whole_word_literal(spark):
    target = spark.createDataFrame([("Price is $5.00 in Cat and catalog",)], "text string")
    lookup = spark.createDataFrame([("cat", "dog"), ("$5.00", "$6 \\E")], "find string, repl string")
    node = FindReplaceNode(
        node_id=34,
        find_field="text",
        search_field="find",
        replace_field="repl",
        find_mode="contains",
        whole_word=True,
        replace_multiple=True,
        case_sensitive=False,
    )
    out = _run("\n".join(find_replace_lines(node, "T", "LK", "OUT")), T=target, LK=lookup)
    assert out.collect()[0]["text"] == "Price is $6 \\E in dog and catalog"


def test_find_replace_any_part_first_found_only(spark):
    target = spark.createDataFrame([("red green red",), ("blue",)], "text string")
    lookup = spark.createDataFrame([("green", "G"), ("red", "R")], "find string, repl string")
    node = FindReplaceNode(
        node_id=35, find_field="text", search_field="find", replace_field="repl", find_mode="contains"
    )
    out = _run("\n".join(find_replace_lines(node, "T", "LK", "OUT")), T=target, LK=lookup)
    assert sorted(r["text"] for r in out.collect()) == ["blue", "red G red"]
