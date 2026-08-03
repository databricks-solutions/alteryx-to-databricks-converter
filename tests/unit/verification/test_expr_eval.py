"""Tests for the pandas expression evaluator."""

from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

from a2d.verification.expr_eval import UnsupportedExpressionError, evaluate_expression


@pytest.fixture
def df():
    return pd.DataFrame({"a": [1, 2, 3], "b": [10, 20, 30], "name": ["Al", "bO", "cc"]})


class TestArithmetic:
    def test_add(self, df):
        assert evaluate_expression("[a] + [b]", df).tolist() == [11, 22, 33]

    def test_multiply_literal(self, df):
        assert evaluate_expression("[a] * 2", df).tolist() == [2, 4, 6]

    def test_precedence(self, df):
        assert evaluate_expression("[a] + [b] * 2", df).tolist() == [21, 42, 63]


class TestComparisonLogical:
    def test_gt(self, df):
        assert evaluate_expression("[a] > 1", df).tolist() == [False, True, True]

    def test_and(self, df):
        assert evaluate_expression("[a] > 1 AND [b] < 30", df).tolist() == [False, True, False]

    def test_or(self, df):
        assert evaluate_expression("[a] = 1 OR [a] = 3", df).tolist() == [True, False, True]


class TestFunctions:
    def test_uppercase(self, df):
        assert evaluate_expression("Uppercase([name])", df).tolist() == ["AL", "BO", "CC"]

    def test_abs(self):
        d = pd.DataFrame({"x": [-1, 2, -3]})
        assert evaluate_expression("Abs([x])", d).tolist() == [1, 2, 3]

    def test_length(self, df):
        assert evaluate_expression("Length([name])", df).tolist() == [2, 2, 2]

    def test_if_then_else(self, df):
        out = evaluate_expression('IF [a] > 1 THEN "hi" ELSE "lo" ENDIF', df)
        assert list(out) == ["lo", "hi", "hi"]


class TestUnsupported:
    def test_unknown_function_raises(self, df):
        with pytest.raises(UnsupportedExpressionError):
            evaluate_expression("SomeAlteryxOnlyФункция([a])", df)

    def test_unknown_field_raises(self, df):
        with pytest.raises(UnsupportedExpressionError):
            evaluate_expression("[nonexistent] + 1", df)
