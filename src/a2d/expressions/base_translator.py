"""Base expression translator with shared visitor dispatch logic.

Concrete translators (PySpark, SQL) override only output-format-specific
methods: ``_visit_FieldRef``, ``_visit_RowRef``, ``_visit_Literal``,
``_visit_FunctionCall``, and the Switch helper.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from a2d.expressions.ast import (
    BinaryOp,
    ComparisonOp,
    Expr,
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
from a2d.expressions.errors import BaseTranslationError
from a2d.expressions.parser import ExpressionParser

# Re-export for backwards compatibility — existing code imports from here.
__all__ = ["BaseExpressionTranslator", "BaseTranslationError"]

# Functions whose return type is always string — used to detect string + concatenation
_STRING_PRODUCING_FUNCTIONS: frozenset[str] = frozenset(
    {
        "datetimeformat",
        "tostring",
        "converttostring",
        "trim",
        "ltrim",
        "rtrim",
        "padleft",
        "padright",
        "substring",
        "mid",
        "left",
        "right",
        "uppercase",
        "lowercase",
        "titlecase",
        "toupper",
        "tolower",
        "replace",
        "findstring",
        "reversestring",
        "stringelement",
        "regexreplace",
        "regexextract",
    }
)


class BaseExpressionTranslator(ABC):
    """Shared dispatch and structural visitors for expression translators."""

    def __init__(self) -> None:
        self._warnings: list[str] = []

    # -- Public API ----------------------------------------------------------

    def translate(self, expr: Expr) -> str:
        """Translate an AST node to a target-format expression string."""
        self._warnings = []
        return self._visit(expr)

    def translate_string(self, expression: str) -> str:
        """Parse and translate an Alteryx expression string.

        Raises ``BaseTranslationError`` (or a subclass) if the expression
        is empty or cannot be parsed/translated.
        """
        if not expression or not expression.strip():
            raise BaseTranslationError("Empty expression — no filter/formula content found in workflow XML")
        parser = ExpressionParser()
        ast = parser.parse(expression)
        return self.translate(ast)

    @property
    def warnings(self) -> list[str]:
        """Return any warnings generated during the last translation."""
        return list(self._warnings)

    # -- Visitor dispatch ----------------------------------------------------

    def _visit(self, node: Expr) -> str:
        method_name = f"_visit_{type(node).__name__}"
        method = getattr(self, method_name, None)
        if method is None:
            raise self._make_error(f"Unsupported AST node type: {type(node).__name__}")
        return method(node)

    @abstractmethod
    def _make_error(self, message: str) -> Exception:
        """Create a format-specific translation error."""

    # -- String-type detection -----------------------------------------------

    def _is_string_expr(self, node: Expr) -> bool:
        """Return True if node statically produces a string value."""
        if isinstance(node, Literal):
            return node.literal_type == "string"
        if isinstance(node, FunctionCall):
            return node.function_name.lower() in _STRING_PRODUCING_FUNCTIONS
        if isinstance(node, BinaryOp) and node.operator == "+":
            return self._is_string_expr(node.left) or self._is_string_expr(node.right)
        return False

    # -- Shared structural visitors -----------------------------------------

    def _visit_BinaryOp(self, node: BinaryOp) -> str:
        left = self._visit(node.left)
        right = self._visit(node.right)
        return f"({left} {node.operator} {right})"

    def _visit_UnaryOp(self, node: UnaryOp) -> str:
        operand = self._visit(node.operand)
        return f"({node.operator}{operand})"

    def _visit_ComparisonOp(self, node: ComparisonOp) -> str:
        left = self._visit(node.left)
        right = self._visit(node.right)
        op = self._cmp_map.get(node.operator, node.operator)
        return f"({left} {op} {right})"

    @property
    @abstractmethod
    def _cmp_map(self) -> dict[str, str]:
        """Map Alteryx comparison operators to target format operators."""

    @abstractmethod
    def _visit_LogicalOp(self, node: LogicalOp) -> str: ...

    @abstractmethod
    def _visit_NotOp(self, node: NotOp) -> str: ...

    @abstractmethod
    def _visit_FieldRef(self, node: FieldRef) -> str: ...

    @abstractmethod
    def _visit_RowRef(self, node: RowRef) -> str: ...

    @abstractmethod
    def _visit_Literal(self, node: Literal) -> str: ...

    @abstractmethod
    def _visit_IfExpr(self, node: IfExpr) -> str: ...

    @abstractmethod
    def _visit_InExpr(self, node: InExpr) -> str: ...

    @abstractmethod
    def _visit_FunctionCall(self, node: FunctionCall) -> str: ...
