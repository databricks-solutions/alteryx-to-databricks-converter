"""Code generated for Alteryx Join and Find Replace, in the PySpark, DLT and SQL outputs.

What the code does on real data is checked in
tests/integration/test_join_find_replace_spark.py (needs Spark).
"""

from __future__ import annotations

import ast

from a2d.generators.find_replace_code import find_replace_lines, problem
from a2d.generators.join_code import join_output_lines
from a2d.generators.sql import _find_replace_sql, _join_select_list
from a2d.ir.nodes import FieldAction, FieldOperation, FindReplaceNode, JoinKey, JoinNode


def _op(name: str, selected: bool = True, rename: str | None = None) -> FieldOperation:
    action = FieldAction.RENAME if rename else (FieldAction.SELECT if selected else FieldAction.DESELECT)
    return FieldOperation(field_name=name, selected=selected, rename_to=rename, action=action)


KEYS = [JoinKey("COMPANY_ID", "COMPANY_ID"), JoinKey("ARTICLE_ID", "ARTICLE_ID")]


class TestJoinPySpark:
    def test_right_side_gets_alteryx_prefix_before_the_join(self):
        node = JoinNode(node_id=25, join_keys=KEYS, select_right=[_op("Right_COMPANY_ID", False)])
        code = "\n".join(join_output_lines(node, "df_10", "df_18", "df_25_join"))
        ast.parse(code)
        assert 'f"Right_{c}" if c in df_10.columns else c' in code
        assert "df_10.join(_r_25," in code
        assert 'F.col("COMPANY_ID") == F.col(_rn_25["COMPANY_ID"])' in code
        assert '.drop("Right_COMPANY_ID")' in code

    def test_only_listed_fields_when_unknown_is_deselected(self):
        node = JoinNode(
            node_id=7,
            join_keys=[JoinKey("K", "K")],
            keep_unlisted=False,
            select_left=[_op("K"), _op("A", True, "A2")],
            select_right=[_op("Right_K", False)],
        )
        code = "\n".join(join_output_lines(node, "a", "b", "out"))
        ast.parse(code)
        assert '.withColumnsRenamed({"A": "A2"})' in code
        assert '.select(F.col("K"), F.col("A2"))' in code

    def test_names_with_dots_are_quoted(self):
        node = JoinNode(node_id=8, join_keys=[JoinKey("a.b", "c d")])
        code = "\n".join(join_output_lines(node, "x", "y", "out"))
        ast.parse(code)
        assert 'F.col("`a.b`")' in code
        assert '_rn_8["c d"].replace' in code


class TestJoinSQL:
    def test_same_named_keys_and_deselected_right_keys(self):
        node = JoinNode(
            node_id=25,
            join_keys=KEYS,
            select_right=[_op("Right_COMPANY_ID", False), _op("Right_ARTICLE_ID", False)],
        )
        sql = _join_select_list(node)
        assert "l.*, r.* EXCEPT (`COMPANY_ID`, `ARTICLE_ID`)" in sql
        assert "AS `Right_" not in sql

    def test_same_named_key_kept_as_right_prefixed(self):
        node = JoinNode(node_id=3, join_keys=[JoinKey("K", "K")])
        sql = _join_select_list(node)
        assert "r.* EXCEPT (`K`), r.`K` AS `Right_K`" in sql

    def test_listed_right_collision_renamed(self):
        node = JoinNode(node_id=4, join_keys=[JoinKey("K", "ID")], select_right=[_op("Right_A", True, "A_right")])
        assert "r.* EXCEPT (`A`), r.`A` AS `A_right`" in _join_select_list(node)

    def test_unknown_deselected_lists_only_selected_fields(self):
        node = JoinNode(
            node_id=5,
            join_keys=[JoinKey("K", "K")],
            keep_unlisted=False,
            select_left=[_op("K"), _op("A", True, "A_left")],
            select_right=[_op("B")],
        )
        assert _join_select_list(node) == "l.`K` AS `K`, l.`A` AS `A_left`, r.`B` AS `B`"


def _fr(**kw) -> FindReplaceNode:
    base = {"node_id": 24, "find_field": "city", "search_field": "code", "replace_field": "name"}
    return FindReplaceNode(**{**base, **kw})


class TestFindReplacePySpark:
    def test_entire_field_replace_is_a_lookup_join(self):
        code = "\n".join(find_replace_lines(_fr(case_sensitive=False), "df_1", "df_2", "df_24"))
        ast.parse(code)
        assert 'F.lower(F.col("code")).alias("_fr_key")' in code
        assert '.dropDuplicates(["_fr_key"])' in code
        assert 'df_1.join(_fr_24, F.lower(F.col("city")) == F.col("_fr_key"), "left")' in code

    def test_any_part_append_builds_a_match_expression(self):
        node = _fr(find_mode="contains", replace_mode="append", append_fields=["name", "region"], whole_word=True)
        code = "\n".join(find_replace_lines(node, "df_1", "df_2", "df_24"))
        ast.parse(code)
        assert ".collect()" in code
        assert "(?<!\\\\S)" in code and "\\\\Q" in code
        assert "for i, name in enumerate(['name', 'region'], start=1):" in code

    def test_problems_are_reported_not_guessed(self):
        assert (
            problem(_fr(find_mode="FindBegin", raw_find_mode="FindBegin"))
            == "find mode 'FindBegin' isn't supported yet"
        )
        assert problem(_fr(search_field="")) == "the find fields aren't set"
        assert problem(_fr(replace_mode="append")) == "no fields to append are set"
        assert problem(_fr()) is None


class TestFindReplaceSQL:
    def test_entire_field_replace(self):
        warnings: list[str] = []
        sql = _find_replace_sql(_fr(), {"Targets": "t1", "Source": "s1"}, warnings)
        assert sql.startswith("SELECT t.* EXCEPT (`city`), CASE WHEN l.`_fr_key` IS NOT NULL")
        assert (
            "FROM t1 t LEFT JOIN (SELECT `code` AS `_fr_key`, FIRST(`name`) AS `_fr_value` FROM s1 GROUP BY `code`)"
            in sql
        )
        assert warnings == []

    def test_any_part_is_refused_with_a_reason(self):
        warnings: list[str] = []
        sql = _find_replace_sql(_fr(find_mode="contains"), {"Targets": "t1", "Source": "s1"}, warnings)
        assert sql.startswith("SELECT 1 WHERE FALSE")
        assert "Use the PySpark output" in warnings[0]

    def test_missing_input_named(self):
        warnings: list[str] = []
        sql = _find_replace_sql(_fr(), {"Targets": "t1"}, warnings)
        assert "R (replace) input missing" in sql
