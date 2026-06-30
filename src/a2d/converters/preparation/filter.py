"""Converter for Alteryx Filter tool -> FilterNode."""

from __future__ import annotations

import html
import re

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get_nested
from a2d.ir.nodes import FilterNode, IRNode
from a2d.parser.schema import ParsedNode

_UNARY_NULL_OPS: dict[str, str] = {
    "IsNull": "IsNull([{field}])",
    "IsNotNull": "!IsNull([{field}])",
    "IsEmpty": "IsEmpty([{field}])",
    "IsNotEmpty": "!IsEmpty([{field}])",
    "IsTrue": "[{field}]",  # Boolean column truthy test
    "IsFalse": "![{field}]",  # Boolean column falsy test
}

# Alteryx UI operators that map to function-style Alteryx expressions.
_FUNC_OPS: dict[str, str] = {
    "Contains": "Contains([{field}], {operand})",
    "DoesNotContain": "!Contains([{field}], {operand})",
    "NotContains": "!Contains([{field}], {operand})",
    "StartsWith": "StartsWith([{field}], {operand})",
    "EndsWith": "EndsWith([{field}], {operand})",
}

# Operators that map directly to Alteryx comparison/equality operators.
_BINARY_OPS: dict[str, str] = {
    "=": "=",
    "==": "=",
    "!=": "!=",
    "<>": "!=",
    "<": "<",
    ">": ">",
    "<=": "<=",
    ">=": ">=",
}


_NUMERIC_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
_FIELD_REF_RE = re.compile(r"^\[[^\]]+\]$")


def _format_operand(raw: str, *, force_string: bool = False) -> str:
    """Quote a simple-mode operand as a string literal unless it's already
    quoted, a numeric literal, or a field reference.

    When ``force_string`` is true, numeric-looking values are still quoted
    (use this for substring-style operators like ``Contains`` where the
    operand is always a string match value).

    Embedded double-quotes inside the operand are escaped via the Alteryx
    doubled-quote convention.
    """
    if raw is None:
        return '""'
    operand = str(raw).strip()
    if not operand:
        return '""'

    # Already a quoted string literal — leave as-is (still needs html unescape upstream).
    if (operand.startswith('"') and operand.endswith('"')) or (operand.startswith("'") and operand.endswith("'")):
        return operand

    # Field reference (e.g. cross-column compare)
    if _FIELD_REF_RE.match(operand):
        return operand

    # Numeric literal — only treated as numeric for binary comparison ops.
    if not force_string and _NUMERIC_RE.match(operand):
        return operand

    # Otherwise treat as string literal — escape internal double quotes.
    escaped = operand.replace('"', '""')
    return f'"{escaped}"'


def _build_simple_expression(cfg: dict) -> str:
    """Build a filter expression from Alteryx simple-mode fields.

    Simple mode stores: Field, Operator, Operands -> Operand
    Example: [Age] > 18

    Some XML variants nest these under a ``<Simple>`` element.

    Handles UI-only operators (``Contains``, ``NotContains``, ``IsTrue`` etc.)
    by translating them into proper Alteryx expression syntax so the downstream
    expression engine can parse them.
    """
    # If fields are nested under a <Simple> element, unwrap first
    simple = cfg.get("Simple", {})
    if isinstance(simple, dict) and simple:
        cfg = simple

    field_name = safe_get_nested(cfg, "Field")
    operator = safe_get_nested(cfg, "Operator")
    operands = cfg.get("Operands", {})

    operand = safe_get_nested(operands, "Operand") if isinstance(operands, dict) else str(operands) if operands else ""

    if not field_name or not operator:
        return ""

    operator = operator.strip()

    # Unary null/empty/boolean operators don't take an operand
    if operator in _UNARY_NULL_OPS:
        return _UNARY_NULL_OPS[operator].format(field=field_name)

    if operator in _FUNC_OPS:
        formatted = _format_operand(html.unescape(operand or ""), force_string=True)
        return _FUNC_OPS[operator].format(field=field_name, operand=formatted)

    if operator in _BINARY_OPS:
        formatted = _format_operand(html.unescape(operand or ""))
        return f"[{field_name}] {_BINARY_OPS[operator]} {formatted}"

    # Fallback: emit as-is and rely on the translator to handle it (or fail
    # with a controlled fallback warning).
    expr = f"[{field_name}] {operator}"
    if operand:
        expr = f"{expr} {operand}"
    return html.unescape(expr)


@ConverterRegistry.register
class FilterConverter(ToolConverter):
    """Converts Alteryx Filter to :class:`FilterNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Filter"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        mode = safe_get_nested(cfg, "Mode", default="Simple")
        mode_lower = mode.lower() if mode else "simple"

        # Always try to get the Expression element first (present in both modes)
        expression = safe_get_nested(cfg, "Expression")
        expression = html.unescape(expression) if expression else ""

        if mode_lower == "custom":
            ir_mode = "custom"
        else:
            ir_mode = "simple"
            # If no top-level expression, try building from Simple mode sub-fields
            if not expression:
                expression = _build_simple_expression(cfg)

        return FilterNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            expression=expression,
            mode=ir_mode,
        )
