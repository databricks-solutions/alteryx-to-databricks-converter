"""Tests for normalize_sql_for_spark in a2d.utils.types."""

from __future__ import annotations

import pytest

from a2d.utils.types import normalize_sql_for_spark


def test_bracket_simple_identifier():
    result, warns = normalize_sql_for_spark("SELECT * FROM [my_table]")
    assert result == "SELECT * FROM `my_table`"
    assert warns == []


def test_bracket_fully_qualified_three_part():
    query = "select [db].[dbo].[tbl].[col] from [db].[dbo].[tbl]"
    result, _ = normalize_sql_for_spark(query)
    assert result == "select `db`.`dbo`.`tbl`.`col` from `db`.`dbo`.`tbl`"


def test_bracket_mixed_unquoted_schema():
    # Pattern seen in the TD workflow: [db].dbo.[table]
    query = "select [1_raw_data].dbo.[my_table].* from [1_raw_data].dbo.[my_table]"
    result, _ = normalize_sql_for_spark(query)
    assert "`1_raw_data`" in result
    assert "`my_table`" in result
    assert "[" not in result


def test_bracket_hyphen_converted_to_underscore():
    result, _ = normalize_sql_for_spark("SELECT * FROM [my-table]")
    assert "`my_table`" in result


def test_bracket_and_double_quote_mixed():
    query = 'select [col1], "col2" from [tbl]'
    result, _ = normalize_sql_for_spark(query)
    assert "`col1`" in result
    assert "`col2`" in result
    assert "[" not in result
    assert '"' not in result


def test_existing_getdate_normalization_still_works():
    query = "SELECT GETDATE(), NOW(), SYSDATE FROM t"
    result, _ = normalize_sql_for_spark(query)
    assert "CURRENT_TIMESTAMP()" in result
    assert "GETDATE" not in result
    assert "SYSDATE" not in result


def test_no_false_positive_on_plain_sql():
    query = "SELECT a, b FROM my_table WHERE x = 1"
    result, _ = normalize_sql_for_spark(query)
    assert result == query


def test_real_world_tsql_query():
    # Representative query from the TD workflow
    query = (
        "SELECT * FROM [4_prod_risk_assessment] .dbo.[4_rap_016_risk_assessment_repository] a"
        " INNER JOIN (SELECT MAX(CAST(ra_campaign_snapshot_id AS INT)) AS max_snapshot"
        " FROM [4_prod_risk_assessment] .dbo.[4_rap_016_risk_assessment_repository]"
        " GROUP BY ra_campaign_year) b ON a.ra_campaign_year = b.ra_campaign_year"
    )
    result, _ = normalize_sql_for_spark(query)
    assert "`4_prod_risk_assessment`" in result
    assert "`4_rap_016_risk_assessment_repository`" in result
    assert "[" not in result
