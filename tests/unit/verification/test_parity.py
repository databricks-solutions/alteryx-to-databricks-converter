"""Tests for the parity engine (DataFrame diff)."""

from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

from a2d.verification.parity import compare_frames


class TestSchemaParity:
    def test_identical_frames_pass(self):
        e = pd.DataFrame({"id": [1, 2, 3], "amt": [10.0, 20.0, 30.0]})
        r = compare_frames(e, e.copy())
        assert r.passed
        assert r.parity_score == pytest.approx(1.0)

    def test_missing_column_fails(self):
        e = pd.DataFrame({"id": [1, 2], "amt": [1.0, 2.0]})
        a = pd.DataFrame({"id": [1, 2]})
        r = compare_frames(e, a)
        assert not r.passed
        assert r.missing_columns == ["amt"]

    def test_extra_column_fails(self):
        e = pd.DataFrame({"id": [1, 2]})
        a = pd.DataFrame({"id": [1, 2], "x": [9, 9]})
        r = compare_frames(e, a)
        assert not r.passed
        assert r.extra_columns == ["x"]

    def test_column_order_ignored(self):
        e = pd.DataFrame({"a": [1], "b": [2]})
        a = pd.DataFrame({"b": [2], "a": [1]})
        assert compare_frames(e, a).passed


class TestRowParity:
    def test_row_order_ignored(self):
        e = pd.DataFrame({"id": [1, 2, 3], "v": ["a", "b", "c"]})
        a = pd.DataFrame({"id": [3, 1, 2], "v": ["c", "a", "b"]})
        assert compare_frames(e, a).passed

    def test_row_count_mismatch_fails(self):
        e = pd.DataFrame({"id": [1, 2, 3]})
        a = pd.DataFrame({"id": [1, 2]})
        r = compare_frames(e, a)
        assert not r.passed
        assert not r.row_count_match
        assert r.unmatched_expected_rows == 1

    def test_duplicate_rows_are_multiset_compared(self):
        e = pd.DataFrame({"id": [1, 1, 2]})
        a = pd.DataFrame({"id": [1, 2, 2]})  # same set, different multiplicity
        r = compare_frames(e, a)
        assert not r.passed
        assert not r.row_set_match


class TestValueParity:
    def test_int_vs_float_equivalent(self):
        e = pd.DataFrame({"amt": [10.0, 20.0]})
        a = pd.DataFrame({"amt": [10, 20]})
        assert compare_frames(e, a).passed

    def test_numeric_tolerance(self):
        e = pd.DataFrame({"amt": [1.0000000], "id": [1]})
        a = pd.DataFrame({"amt": [1.0000001], "id": [1]})
        # within rel_tol default
        assert compare_frames(e, a).passed

    def test_value_mismatch_reported(self):
        e = pd.DataFrame({"id": [1, 2, 3], "amt": [10.0, 20.0, 30.0]})
        a = pd.DataFrame({"id": [1, 2, 3], "amt": [10.0, 20.0, 99.0]})
        r = compare_frames(e, a)
        assert not r.passed
        amt = next(c for c in r.column_parities if c.column == "amt")
        assert amt.mismatch_count == 1
        assert amt.sample_mismatches

    def test_whitespace_normalized(self):
        e = pd.DataFrame({"name": ["alice", "bob"]})
        a = pd.DataFrame({"name": [" alice ", "bob"]})
        assert compare_frames(e, a).passed

    def test_null_equality(self):
        e = pd.DataFrame({"v": [1.0, None, 3.0]})
        a = pd.DataFrame({"v": [1.0, None, 3.0]})
        assert compare_frames(e, a).passed


class TestReportSerialization:
    def test_to_dict_shape(self):
        e = pd.DataFrame({"id": [1]})
        r = compare_frames(e, e.copy())
        d = r.to_dict()
        assert set(d) >= {"passed", "parity_score", "schema", "rows", "columns", "notes"}

    def test_summary_string(self):
        e = pd.DataFrame({"id": [1, 2]})
        assert "PASS" in compare_frames(e, e.copy()).summary()
