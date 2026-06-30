"""Alteryx expression AST (Abstract Syntax Tree) node classes.

Defines the tree structure produced by the expression parser and consumed
by the PySpark and SQL translators.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field


@dataclass
class Expr(ABC):
    """Base expression node."""

    pass


@dataclass
class FieldRef(Expr):
    """Reference to a field/column: [FieldName]."""

    field_name: str


@dataclass
class RowRef(Expr):
    """Multi-row field reference: [Row-1:FieldName].

    Used in Alteryx multi-row formula tools for accessing
    values in previous or subsequent rows.
    """

    field_name: str
    row_offset: int  # -1 for previous, +1 for next


@dataclass
class Literal(Expr):
    """A literal value: string, number, boolean, or null."""

    value: str | int | float | bool | None
    literal_type: str  # "string", "number", "boolean", "null"


@dataclass
class BinaryOp(Expr):
    """Binary arithmetic operation: left op right."""

    left: Expr
    operator: str  # "+", "-", "*", "/", "%"
    right: Expr


@dataclass
class UnaryOp(Expr):
    """Unary operation (e.g. negation): op operand."""

    operator: str  # "-"
    operand: Expr


@dataclass
class ComparisonOp(Expr):
    """Comparison operation: left op right."""

    left: Expr
    operator: str  # "=", "!=", ">", "<", ">=", "<="
    right: Expr


@dataclass
class LogicalOp(Expr):
    """Logical binary operation: left AND/OR right."""

    left: Expr
    operator: str  # "AND", "OR"
    right: Expr


@dataclass
class NotOp(Expr):
    """Logical NOT: NOT operand."""

    operand: Expr


@dataclass
class FunctionCall(Expr):
    """Function call: FunctionName(arg1, arg2, ...)."""

    function_name: str
    arguments: list[Expr] = field(default_factory=list)


@dataclass
class IfExpr(Expr):
    """IF/THEN/ELSEIF/ELSE/ENDIF expression.

    Represents Alteryx conditional expressions like:
        IF [X] > 0 THEN "positive"
        ELSEIF [X] = 0 THEN "zero"
        ELSE "negative"
        ENDIF
    """

    condition: Expr
    then_expr: Expr
    elseif_clauses: list[tuple[Expr, Expr]] = field(default_factory=list)
    else_expr: Expr | None = None


@dataclass
class InExpr(Expr):
    """IN expression: value IN (item1, item2, ...).

    Represents membership testing in Alteryx.
    """

    value: Expr
    items: list[Expr] = field(default_factory=list)
