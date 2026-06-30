"""Tests for the Alteryx expression parser."""

from __future__ import annotations

import pytest

from a2d.expressions.ast import (
    BinaryOp,
    ComparisonOp,
    FieldRef,
    FunctionCall,
    IfExpr,
    InExpr,
    Literal,
    LogicalOp,
    NotOp,
    RowRef,
    UnaryOp,
)
from a2d.expressions.parser import ExpressionParser, ParserError


@pytest.fixture
def parser() -> ExpressionParser:
    return ExpressionParser()


class TestSimpleComparisons:
    """Test parsing of simple comparison expressions."""

    def test_field_greater_than_number(self, parser: ExpressionParser) -> None:
        ast = parser.parse("[Age] > 25")
        assert isinstance(ast, ComparisonOp)
        assert isinstance(ast.left, FieldRef)
        assert ast.left.field_name == "Age"
        assert ast.operator == ">"
        assert isinstance(ast.right, Literal)
        assert ast.right.value == 25

    def test_field_equals_string(self, parser: ExpressionParser) -> None:
        ast = parser.parse('[Name] = "Smith"')
        assert isinstance(ast, ComparisonOp)
        assert ast.operator == "="
        assert isinstance(ast.right, Literal)
        assert ast.right.value == "Smith"
        assert ast.right.literal_type == "string"

    def test_not_equal(self, parser: ExpressionParser) -> None:
        ast = parser.parse('[Status] != "Active"')
        assert isinstance(ast, ComparisonOp)
        assert ast.operator == "!="

    def test_less_equal(self, parser: ExpressionParser) -> None:
        ast = parser.parse("[Score] <= 100")
        assert isinstance(ast, ComparisonOp)
        assert ast.operator == "<="


class TestArithmetic:
    """Test parsing of arithmetic expressions with correct precedence."""

    def test_multiplication(self, parser: ExpressionParser) -> None:
        ast = parser.parse("[Price] * [Quantity]")
        assert isinstance(ast, BinaryOp)
        assert ast.operator == "*"
        assert isinstance(ast.left, FieldRef)
        assert isinstance(ast.right, FieldRef)

    def test_addition(self, parser: ExpressionParser) -> None:
        ast = parser.parse("[A] + [B]")
        assert isinstance(ast, BinaryOp)
        assert ast.operator == "+"

    def test_precedence_mul_over_add(self, parser: ExpressionParser) -> None:
        # [A] + [B] * [C] should parse as [A] + ([B] * [C])
        ast = parser.parse("[A] + [B] * [C]")
        assert isinstance(ast, BinaryOp)
        assert ast.operator == "+"
        assert isinstance(ast.right, BinaryOp)
        assert ast.right.operator == "*"

    def test_parenthesized_precedence(self, parser: ExpressionParser) -> None:
        # ([A] + [B]) * [C]
        ast = parser.parse("([A] + [B]) * [C]")
        assert isinstance(ast, BinaryOp)
        assert ast.operator == "*"
        assert isinstance(ast.left, BinaryOp)
        assert ast.left.operator == "+"

    def test_unary_minus(self, parser: ExpressionParser) -> None:
        ast = parser.parse("-[Value]")
        assert isinstance(ast, UnaryOp)
        assert ast.operator == "-"
        assert isinstance(ast.operand, FieldRef)


class TestFunctionCalls:
    """Test parsing of function calls."""

    def test_single_arg_function(self, parser: ExpressionParser) -> None:
        ast = parser.parse("ABS([Value])")
        assert isinstance(ast, FunctionCall)
        assert ast.function_name == "ABS"
        assert len(ast.arguments) == 1
        assert isinstance(ast.arguments[0], FieldRef)

    def test_multi_arg_function(self, parser: ExpressionParser) -> None:
        ast = parser.parse('Contains([Name], "Smith")')
        assert isinstance(ast, FunctionCall)
        assert ast.function_name == "Contains"
        assert len(ast.arguments) == 2
        assert isinstance(ast.arguments[0], FieldRef)
        assert isinstance(ast.arguments[1], Literal)

    def test_no_arg_function(self, parser: ExpressionParser) -> None:
        ast = parser.parse("DateTimeNow()")
        assert isinstance(ast, FunctionCall)
        assert ast.function_name == "DateTimeNow"
        assert len(ast.arguments) == 0

    def test_nested_function_calls(self, parser: ExpressionParser) -> None:
        ast = parser.parse("Trim(LowerCase([Name]))")
        assert isinstance(ast, FunctionCall)
        assert ast.function_name == "Trim"
        assert len(ast.arguments) == 1
        inner = ast.arguments[0]
        assert isinstance(inner, FunctionCall)
        assert inner.function_name == "LowerCase"


class TestIfExpressions:
    """Test parsing of IF/THEN/ELSE/ENDIF blocks."""

    def test_simple_if(self, parser: ExpressionParser) -> None:
        ast = parser.parse('IF [Status] = "Active" THEN 1 ELSE 0 ENDIF')
        assert isinstance(ast, IfExpr)
        assert isinstance(ast.condition, ComparisonOp)
        assert isinstance(ast.then_expr, Literal)
        assert ast.then_expr.value == 1
        assert isinstance(ast.else_expr, Literal)
        assert ast.else_expr.value == 0
        assert len(ast.elseif_clauses) == 0

    def test_if_without_else(self, parser: ExpressionParser) -> None:
        ast = parser.parse("IF [A] > 0 THEN 1 ENDIF")
        assert isinstance(ast, IfExpr)
        assert ast.else_expr is None

    def test_if_elseif_else(self, parser: ExpressionParser) -> None:
        ast = parser.parse('IF [A] > 0 THEN "pos" ELSEIF [A] = 0 THEN "zero" ELSE "neg" ENDIF')
        assert isinstance(ast, IfExpr)
        assert len(ast.elseif_clauses) == 1
        elseif_cond, elseif_then = ast.elseif_clauses[0]
        assert isinstance(elseif_cond, ComparisonOp)
        assert isinstance(elseif_then, Literal)
        assert elseif_then.value == "zero"
        assert isinstance(ast.else_expr, Literal)
        assert ast.else_expr.value == "neg"

    def test_multiple_elseif(self, parser: ExpressionParser) -> None:
        ast = parser.parse(
            'IF [X] = 1 THEN "one" ELSEIF [X] = 2 THEN "two" ELSEIF [X] = 3 THEN "three" ELSE "other" ENDIF'
        )
        assert isinstance(ast, IfExpr)
        assert len(ast.elseif_clauses) == 2


class TestLogicalExpressions:
    """Test parsing of logical expressions."""

    def test_and(self, parser: ExpressionParser) -> None:
        ast = parser.parse("[A] > 0 AND [B] < 100")
        assert isinstance(ast, LogicalOp)
        assert ast.operator == "AND"
        assert isinstance(ast.left, ComparisonOp)
        assert isinstance(ast.right, ComparisonOp)

    def test_or(self, parser: ExpressionParser) -> None:
        ast = parser.parse('[Status] = "A" OR [Status] = "B"')
        assert isinstance(ast, LogicalOp)
        assert ast.operator == "OR"

    def test_not(self, parser: ExpressionParser) -> None:
        ast = parser.parse("NOT IsNull([Field])")
        assert isinstance(ast, NotOp)
        assert isinstance(ast.operand, FunctionCall)

    def test_precedence_and_before_or(self, parser: ExpressionParser) -> None:
        # A OR B AND C should parse as A OR (B AND C)
        ast = parser.parse("[A] = 1 OR [B] = 2 AND [C] = 3")
        assert isinstance(ast, LogicalOp)
        assert ast.operator == "OR"
        assert isinstance(ast.right, LogicalOp)
        assert ast.right.operator == "AND"


class TestInExpressions:
    """Test parsing of IN expressions."""

    def test_in_with_strings(self, parser: ExpressionParser) -> None:
        ast = parser.parse('[Color] IN ("Red", "Blue", "Green")')
        assert isinstance(ast, InExpr)
        assert isinstance(ast.value, FieldRef)
        assert ast.value.field_name == "Color"
        assert len(ast.items) == 3
        assert all(isinstance(i, Literal) for i in ast.items)

    def test_in_with_numbers(self, parser: ExpressionParser) -> None:
        ast = parser.parse("[Code] IN (1, 2, 3)")
        assert isinstance(ast, InExpr)
        assert len(ast.items) == 3


class TestLiterals:
    """Test parsing of various literal types."""

    def test_true(self, parser: ExpressionParser) -> None:
        ast = parser.parse("TRUE")
        assert isinstance(ast, Literal)
        assert ast.value is True
        assert ast.literal_type == "boolean"

    def test_false(self, parser: ExpressionParser) -> None:
        ast = parser.parse("FALSE")
        assert isinstance(ast, Literal)
        assert ast.value is False

    def test_null(self, parser: ExpressionParser) -> None:
        ast = parser.parse("NULL")
        assert isinstance(ast, Literal)
        assert ast.value is None
        assert ast.literal_type == "null"

    def test_decimal_number(self, parser: ExpressionParser) -> None:
        ast = parser.parse("3.14")
        assert isinstance(ast, Literal)
        assert ast.value == 3.14
        assert ast.literal_type == "number"


class TestRowReferences:
    """Test parsing of multi-row references."""

    def test_previous_row(self, parser: ExpressionParser) -> None:
        ast = parser.parse("[Row-1:Amount]")
        assert isinstance(ast, RowRef)
        assert ast.field_name == "Amount"
        assert ast.row_offset == -1

    def test_next_row(self, parser: ExpressionParser) -> None:
        ast = parser.parse("[Row+1:Amount]")
        assert isinstance(ast, RowRef)
        assert ast.field_name == "Amount"
        assert ast.row_offset == 1


class TestErrorHandling:
    """Test that the parser raises appropriate errors."""

    def test_missing_endif(self, parser: ExpressionParser) -> None:
        with pytest.raises(ParserError):
            parser.parse('IF [A] = 1 THEN "yes"')

    def test_unexpected_token(self, parser: ExpressionParser) -> None:
        with pytest.raises(ParserError):
            parser.parse("* [A]")

    def test_unclosed_paren(self, parser: ExpressionParser) -> None:
        with pytest.raises(ParserError):
            parser.parse("([A] + [B]")

    def test_empty_string_raises_parser_error(self, parser: ExpressionParser) -> None:
        with pytest.raises(ParserError):
            parser.parse("")

    def test_parser_error_is_base_translation_error(self) -> None:
        """ParserError should be catchable by except BaseTranslationError."""
        from a2d.expressions.base_translator import BaseTranslationError

        assert issubclass(ParserError, BaseTranslationError)

    def test_parser_error_caught_by_base_translation_error(self, parser: ExpressionParser) -> None:
        """Verify generators' except BaseTranslationError catches ParserError."""
        from a2d.expressions.base_translator import BaseTranslationError

        with pytest.raises(BaseTranslationError):
            parser.parse("")
