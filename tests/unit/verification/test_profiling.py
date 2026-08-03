"""Tests for the data-profiling pass."""

from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

from a2d.verification.profiling import profile_csv, profile_dataframe


class TestTypeInference:
    def test_integer_from_string_column(self):
        df = pd.DataFrame({"id": ["1", "2", "3"]})
        p = profile_dataframe(df)
        assert p.columns[0].logical_type == "integer"
        assert p.columns[0].spark_type == "BIGINT"

    def test_double_from_string_column(self):
        df = pd.DataFrame({"amt": ["1.5", "2.0", "3.25"]})
        assert profile_dataframe(df).columns[0].logical_type == "double"

    def test_boolean(self):
        df = pd.DataFrame({"flag": ["true", "false", "TRUE"]})
        assert profile_dataframe(df).columns[0].logical_type == "boolean"

    def test_date_vs_timestamp(self):
        df = pd.DataFrame(
            {
                "d": ["2024-01-01", "2024-06-15"],
                "ts": ["2024-01-01 08:30:00", "2024-06-15 12:00:00"],
            }
        )
        cols = {c.name: c.logical_type for c in profile_dataframe(df).columns}
        assert cols["d"] == "date"
        assert cols["ts"] == "timestamp"

    def test_string_fallback(self):
        df = pd.DataFrame({"name": ["Alice", "Bob", "Carol"]})
        assert profile_dataframe(df).columns[0].logical_type == "string"

    def test_mixed_numeric_and_text_is_string(self):
        df = pd.DataFrame({"x": ["1", "two", "3"]})
        assert profile_dataframe(df).columns[0].logical_type == "string"

    def test_native_pandas_dtypes_respected(self):
        df = pd.DataFrame({"i": [1, 2], "f": [1.0, 2.0], "b": [True, False]})
        cols = {c.name: c.logical_type for c in profile_dataframe(df).columns}
        assert cols == {"i": "integer", "f": "double", "b": "boolean"}

    def test_all_null_column_is_empty(self):
        df = pd.DataFrame({"blank": [None, None]})
        assert profile_dataframe(df).columns[0].logical_type == "empty"


class TestStatistics:
    def test_null_rate(self):
        df = pd.DataFrame({"v": ["a", None, "c", None]})
        col = profile_dataframe(df).columns[0]
        assert col.null_count == 2
        assert col.null_rate == pytest.approx(0.5)

    def test_distinct_count(self):
        df = pd.DataFrame({"v": ["a", "a", "b", None]})
        assert profile_dataframe(df).columns[0].distinct_count == 2

    def test_numeric_min_max(self):
        df = pd.DataFrame({"n": ["10", "5", "30"]})
        col = profile_dataframe(df).columns[0]
        assert col.min_value == 5
        assert col.max_value == 30

    def test_double_min_max(self):
        df = pd.DataFrame({"n": ["1.5", "0.25", "9.75"]})
        col = profile_dataframe(df).columns[0]
        assert col.min_value == pytest.approx(0.25)
        assert col.max_value == pytest.approx(9.75)

    def test_string_has_no_min_max(self):
        df = pd.DataFrame({"s": ["b", "a", "c"]})
        col = profile_dataframe(df).columns[0]
        assert col.min_value is None and col.max_value is None

    def test_row_count(self):
        df = pd.DataFrame({"a": [1, 2, 3, 4]})
        assert profile_dataframe(df).row_count == 4


class TestSchemaAndSerialization:
    def test_spark_schema_ddl(self):
        df = pd.DataFrame({"id": ["1"], "name": ["x"], "amt": ["1.5"]})
        ddl = profile_dataframe(df).spark_schema_ddl()
        assert "`id` BIGINT" in ddl
        assert "`name` STRING" in ddl
        assert "`amt` DOUBLE" in ddl

    def test_to_dict_shape(self):
        df = pd.DataFrame({"id": ["1", "2"]})
        d = profile_dataframe(df, source="s").to_dict()
        assert d["source"] == "s"
        assert d["row_count"] == 2
        assert "spark_schema_ddl" in d
        assert d["columns"][0]["name"] == "id"


class TestCsv:
    def test_profile_csv(self, tmp_path):
        p = tmp_path / "d.csv"
        p.write_text("id,amount,name\n1,100.5,Alice\n2,200.0,\n")
        prof = profile_csv(str(p))
        assert prof.row_count == 2
        cols = {c.name: c.logical_type for c in prof.columns}
        assert cols == {"id": "integer", "amount": "double", "name": "string"}
        name_col = next(c for c in prof.columns if c.name == "name")
        assert name_col.null_count == 1
