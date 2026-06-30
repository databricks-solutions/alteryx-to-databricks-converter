"""Spark SQL translator.

Walks an Alteryx expression AST and emits a Spark SQL string.  This is the
SQL counterpart to :mod:`a2d.expressions.translator` (which emits PySpark
column-expression code).
"""

from __future__ import annotations

from a2d.expressions.ast import (
    BinaryOp,
    FieldRef,
    FunctionCall,
    IfExpr,
    InExpr,
    Literal,
    LogicalOp,
    NotOp,
    RowRef,
)
from a2d.expressions.base_translator import BaseExpressionTranslator, BaseTranslationError
from a2d.expressions.functions import get_function_mapping
from a2d.utils.types import alteryx_fmt_to_spark


class SQLTranslationError(BaseTranslationError):
    """Raised when the SQL translator cannot handle an AST node."""


# Map Alteryx comparison operators to SQL operators
_SQL_CMP_MAP = {
    "=": "=",
    "!=": "!=",
    "<>": "!=",
    ">": ">",
    "<": "<",
    ">=": ">=",
    "<=": "<=",
}


class SparkSQLTranslator(BaseExpressionTranslator):
    """Translates Alteryx expression AST to Spark SQL strings.

    Usage::

        translator = SparkSQLTranslator()
        sql = translator.translate_string('[Age] > 25')
        # -> '`Age` > 25'
    """

    def _make_error(self, message: str) -> Exception:
        return SQLTranslationError(message)

    @property
    def _cmp_map(self) -> dict[str, str]:
        return _SQL_CMP_MAP

    # -- Format-specific visitors -------------------------------------------

    def _visit_BinaryOp(self, node: BinaryOp) -> str:
        left = self._visit(node.left)
        right = self._visit(node.right)
        if node.operator == "+" and (self._is_string_expr(node.left) or self._is_string_expr(node.right)):
            return f"CONCAT({left}, {right})"
        return f"({left} {node.operator} {right})"

    def _visit_FieldRef(self, node: FieldRef) -> str:
        return f"`{node.field_name}`"

    def _visit_RowRef(self, node: RowRef) -> str:
        offset = node.row_offset
        if offset < 0:
            return f"LAG(`{node.field_name}`, {abs(offset)}) OVER (window)"
        return f"LEAD(`{node.field_name}`, {offset}) OVER (window)"

    def _visit_Literal(self, node: Literal) -> str:
        if node.literal_type == "string":
            escaped = str(node.value).replace("'", "''").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
            return f"'{escaped}'"
        if node.literal_type == "number":
            return str(node.value)
        if node.literal_type == "boolean":
            return "TRUE" if node.value else "FALSE"
        if node.literal_type == "null":
            return "NULL"
        raise SQLTranslationError(f"Unknown literal type: {node.literal_type}")

    def _visit_LogicalOp(self, node: LogicalOp) -> str:
        left = self._visit(node.left)
        right = self._visit(node.right)
        return f"({left} {node.operator} {right})"

    def _visit_NotOp(self, node: NotOp) -> str:
        operand = self._visit(node.operand)
        return f"NOT ({operand})"

    def _visit_FunctionCall(self, node: FunctionCall) -> str:
        mapping = get_function_mapping(node.function_name)

        if mapping is None or mapping.sql_template is None:
            translated_args = [self._visit(a) for a in node.arguments]
            self._warnings.append(f"No SQL template for function: {node.function_name}")
            args = ", ".join(translated_args)
            return f"{node.function_name}({args})"

        # Validate argument count
        n_args = len(node.arguments)
        if n_args < mapping.min_args:
            self._warnings.append(f"{node.function_name}() expects at least {mapping.min_args} arg(s), got {n_args}")
        if mapping.max_args is not None and n_args > mapping.max_args:
            self._warnings.append(f"{node.function_name}() expects at most {mapping.max_args} arg(s), got {n_args}")

        # Translate args, handling raw_string_args (emit as unquoted string values)
        translated_args = []
        for i, arg in enumerate(node.arguments):
            if i in mapping.raw_string_args and isinstance(arg, Literal) and arg.literal_type == "string":
                # For SQL, raw_string_args still need to be quoted strings, but we
                # convert Alteryx date format tokens to Spark format patterns.
                raw_val = str(arg.value)
                if node.function_name.lower() in ("datetimeformat", "datetimeparse", "todate", "todatetime") and i == 1:
                    raw_val = alteryx_fmt_to_spark(raw_val)
                escaped_val = raw_val.replace("'", "''")
                translated_args.append(f"'{escaped_val}'")
            else:
                translated_args.append(self._visit(arg))

        # Special case: Switch -> CASE expression
        if mapping.sql_template == "__SWITCH__":
            return self._translate_switch_sql(translated_args)

        template = mapping.sql_template

        # Handle variable-args placeholder
        if "{args}" in template:
            return template.replace("{args}", ", ".join(translated_args))

        # Substitute positional placeholders
        result = template
        for i, arg_str in enumerate(translated_args):
            result = result.replace(f"{{{i}}}", arg_str)

        # Strip any unsubstituted trailing-optional placeholders (e.g. ", {1}")
        # so 1-arg calls to functions with an optional 2nd arg work cleanly.
        import re as _re

        result = _re.sub(r",\s*\{\d+\}", "", result)

        return result

    def _translate_switch_sql(self, args: list[str]) -> str:
        """Translate Switch(value, default, val1, res1, ...) to SQL CASE."""
        if len(args) < 2:
            return "NULL"
        value = args[0]
        default = args[1]
        pairs = list(zip(args[2::2], args[3::2], strict=False))
        if not pairs:
            return default
        result = f"CASE {value}"
        for val, res in pairs:
            result += f" WHEN {val} THEN {res}"
        result += f" ELSE {default} END"
        return result

    def _visit_IfExpr(self, node: IfExpr) -> str:
        cond = self._visit(node.condition)
        then = self._visit(node.then_expr)
        result = f"CASE WHEN {cond} THEN {then}"

        for elseif_cond, elseif_then in node.elseif_clauses:
            ec = self._visit(elseif_cond)
            et = self._visit(elseif_then)
            result += f" WHEN {ec} THEN {et}"

        if node.else_expr is not None:
            else_val = self._visit(node.else_expr)
            result += f" ELSE {else_val}"

        result += " END"
        return result

    def _visit_InExpr(self, node: InExpr) -> str:
        value = self._visit(node.value)
        items = ", ".join(self._visit(item) for item in node.items)
        return f"{value} IN ({items})"
