"""Evaluate Alteryx expressions against a pandas DataFrame.

Reuses the existing expression parser (:mod:`a2d.expressions.parser`) to build
the shared AST, then walks it into vectorized pandas operations. This is an
*independent* evaluation path from the PySpark/SQL translators — that
independence is what makes it useful as an equivalence reference.

Only the common subset of functions is implemented. Anything unsupported raises
:class:`UnsupportedExpressionError` so the caller can record a clean "skipped" rather
than silently producing a wrong answer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
from a2d.expressions.parser import ExpressionParser

if TYPE_CHECKING:
    import pandas as pd


class UnsupportedExpressionError(Exception):
    """Raised when the reference evaluator cannot handle an expression node."""


def evaluate_expression(expression: str, df: pd.DataFrame) -> pd.Series:
    """Parse and evaluate an Alteryx expression to a pandas Series over ``df``."""
    parser = ExpressionParser()
    ast = parser.parse(expression)  # may raise BaseTranslationError
    return _ExprEvaluator(df).eval(ast)


class _ExprEvaluator:
    """Walks the shared expression AST into pandas Series operations."""

    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df

    def eval(self, node: Expr) -> Any:
        method = getattr(self, f"_eval_{type(node).__name__}", None)
        if method is None:
            raise UnsupportedExpressionError(f"No reference evaluator for {type(node).__name__}")
        return method(node)

    # -- Leaves --

    def _eval_FieldRef(self, node: FieldRef) -> pd.Series:
        if node.field_name not in self.df.columns:
            raise UnsupportedExpressionError(f"Unknown field [{node.field_name}]")
        return self.df[node.field_name]

    def _eval_RowRef(self, node: RowRef) -> Any:
        # Multi-row references are out of scope for the reference executor.
        raise UnsupportedExpressionError("Multi-row references not supported in reference executor")

    def _eval_Literal(self, node: Literal) -> Any:
        return node.value

    # -- Operators --

    def _eval_BinaryOp(self, node: BinaryOp) -> Any:
        left = self.eval(node.left)
        right = self.eval(node.right)
        op = node.operator
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            return left / right
        if op == "%":
            return left % right
        raise UnsupportedExpressionError(f"Unsupported binary operator {op!r}")

    def _eval_UnaryOp(self, node: UnaryOp) -> Any:
        operand = self.eval(node.operand)
        if node.operator == "-":
            return -operand
        raise UnsupportedExpressionError(f"Unsupported unary operator {node.operator!r}")

    def _eval_ComparisonOp(self, node: ComparisonOp) -> Any:
        left = self.eval(node.left)
        right = self.eval(node.right)
        op = node.operator
        if op in ("=", "=="):
            return left == right
        if op in ("!=", "<>"):
            return left != right
        if op == ">":
            return left > right
        if op == "<":
            return left < right
        if op == ">=":
            return left >= right
        if op == "<=":
            return left <= right
        raise UnsupportedExpressionError(f"Unsupported comparison {op!r}")

    def _eval_LogicalOp(self, node: LogicalOp) -> Any:
        left = self.eval(node.left)
        right = self.eval(node.right)
        if node.operator.upper() == "AND":
            return left & right
        if node.operator.upper() == "OR":
            return left | right
        raise UnsupportedExpressionError(f"Unsupported logical operator {node.operator!r}")

    def _eval_NotOp(self, node: NotOp) -> Any:
        return ~self.eval(node.operand)

    def _eval_InExpr(self, node: InExpr) -> Any:
        value = self.eval(node.value)
        items = [self.eval(i) for i in node.items]
        return value.isin(items)

    def _eval_IfExpr(self, node: IfExpr) -> Any:
        import numpy as np

        cond = self.eval(node.condition)
        then_val = self.eval(node.then_expr)
        # Build from the ELSE outward so earlier clauses take precedence.
        result = self.eval(node.else_expr) if node.else_expr is not None else None
        for elif_cond, elif_then in reversed(node.elseif_clauses):
            result = np.where(self._to_array(self.eval(elif_cond)), self.eval(elif_then), result)
        return np.where(self._to_array(cond), then_val, result)

    def _to_array(self, v: Any):
        import pandas as pd

        if isinstance(v, pd.Series):
            return v.fillna(False).to_numpy()
        return v

    # -- Functions (common subset) --

    def _eval_FunctionCall(self, node: FunctionCall) -> Any:
        import pandas as pd

        name = node.function_name.upper()
        args = [self.eval(a) for a in node.arguments]

        def s(x: Any) -> pd.Series:
            """Coerce a scalar to a Series aligned to the frame index."""
            if isinstance(x, pd.Series):
                return x
            return pd.Series([x] * len(self.df), index=self.df.index)

        # String functions
        if name == "UPPERCASE":
            return s(args[0]).astype("string").str.upper()
        if name == "LOWERCASE":
            return s(args[0]).astype("string").str.lower()
        if name == "TRIM":
            return s(args[0]).astype("string").str.strip()
        if name == "LENGTH":
            return s(args[0]).astype("string").str.len()
        if name in ("TRIMLEFT", "LTRIM"):
            return s(args[0]).astype("string").str.lstrip()
        if name in ("TRIMRIGHT", "RTRIM"):
            return s(args[0]).astype("string").str.rstrip()
        if name == "SUBSTRING":
            start = int(args[1]) if len(args) > 1 else 0
            length = int(args[2]) if len(args) > 2 else None
            end = start + length if length is not None else None
            return s(args[0]).astype("string").str.slice(start, end)
        if name == "CONTAINS":
            return s(args[0]).astype("string").str.contains(str(args[1]), regex=False, na=False)
        if name == "REPLACE":
            return s(args[0]).astype("string").str.replace(str(args[1]), str(args[2]), regex=False)

        # Numeric functions
        if name == "ABS":
            return s(args[0]).abs()
        if name == "ROUND":
            ndigits = int(args[1]) if len(args) > 1 else 0
            return s(args[0]).round(ndigits)
        if name == "CEIL":
            import numpy as np

            return pd.Series(np.ceil(s(args[0]).astype(float)), index=self.df.index)
        if name == "FLOOR":
            import numpy as np

            return pd.Series(np.floor(s(args[0]).astype(float)), index=self.df.index)
        if name in ("POW", "POWER"):
            return s(args[0]) ** args[1]
        if name == "SQRT":
            import numpy as np

            return pd.Series(np.sqrt(s(args[0]).astype(float)), index=self.df.index)

        # Null handling
        if name == "ISNULL":
            return s(args[0]).isna()
        if name in ("ISEMPTY",):
            col = s(args[0]).astype("string")
            return col.isna() | (col.str.len() == 0)

        raise UnsupportedExpressionError(f"Unsupported function {node.function_name}()")
