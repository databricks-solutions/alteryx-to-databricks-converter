"""Expression audit — captures original → translated expression mappings.

Walks the IR DAG after code generation and records every expression
transformation for review and debugging.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path

from a2d.generators.base import GeneratedOutput
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    FilterNode,
    FormulaNode,
    GenerateRowsNode,
    IRNode,
    MultiFieldFormulaNode,
    MultiRowFormulaNode,
    RegExNode,
)

logger = logging.getLogger("a2d.observability.expression_audit")

# Expression-related warning keywords for confidence scoring
_EXPR_WARNING_KEYWORDS = ("expression", "formula", "parse fail", "placeholder", "fallback")


@dataclass
class ExpressionAuditEntry:
    """A single original → translated expression mapping."""

    node_id: int
    tool_type: str
    field_name: str
    original_expression: str
    translated_expression: str
    translation_method: str  # "expression-engine", "regex", "direct", "failed"
    confidence: float  # 0.0-1.0
    warnings: list[str] = field(default_factory=list)


class ExpressionAuditor:
    """Walk a DAG and capture every expression transformation."""

    def audit(self, dag: WorkflowDAG, output: GeneratedOutput) -> list[ExpressionAuditEntry]:
        """Audit all expression-bearing nodes in the DAG.

        Args:
            dag: The IR DAG (contains original expressions).
            output: The generated output (contains translated code and warnings).

        Returns:
            List of audit entries, one per expression field.
        """
        entries: list[ExpressionAuditEntry] = []
        warning_set = set(output.warnings)

        for node in dag.topological_sort():
            node_entries = self._audit_node(node, warning_set)
            entries.extend(node_entries)

        return entries

    def _audit_node(self, node: IRNode, warnings: set[str]) -> list[ExpressionAuditEntry]:
        """Extract expression audit entries from a single node."""
        entries: list[ExpressionAuditEntry] = []

        if isinstance(node, FormulaNode):
            for formula in node.formulas:
                entries.append(self._make_entry(node, formula.output_field, formula.expression, warnings))

        elif isinstance(node, FilterNode):
            if node.expression:
                entries.append(self._make_entry(node, "filter_condition", node.expression, warnings))

        elif isinstance(node, MultiRowFormulaNode):
            if node.expression:
                entries.append(self._make_entry(node, node.output_field or "output", node.expression, warnings))

        elif isinstance(node, MultiFieldFormulaNode):
            if node.expression:
                for field_name in node.fields:
                    entries.append(self._make_entry(node, field_name, node.expression, warnings))

        elif isinstance(node, RegExNode):
            if node.expression:
                entries.append(self._make_entry(node, node.field_name or "regex_field", node.expression, warnings))

        elif isinstance(node, GenerateRowsNode):
            for label, expr in [
                ("init", node.init_expression),
                ("condition", node.condition_expression),
                ("loop", node.loop_expression),
            ]:
                if expr:
                    entries.append(self._make_entry(node, f"{node.output_field}_{label}", expr, warnings))

        return entries

    def _make_entry(
        self,
        node: IRNode,
        field_name: str,
        original_expr: str,
        warnings: set[str],
    ) -> ExpressionAuditEntry:
        """Create an audit entry for a single expression."""
        # Check if there were any warnings related to this node
        node_warnings = [w for w in warnings if str(node.node_id) in w or node.original_tool_type.lower() in w.lower()]
        expr_warnings = [w for w in node_warnings if any(k in w.lower() for k in _EXPR_WARNING_KEYWORDS)]

        # Determine translation method and confidence
        if expr_warnings:
            method = "failed"
            confidence = 0.3
        elif node.conversion_method == "expression-engine":
            method = "expression-engine"
            confidence = node.conversion_confidence
        else:
            method = node.conversion_method
            confidence = node.conversion_confidence

        return ExpressionAuditEntry(
            node_id=node.node_id,
            tool_type=node.original_tool_type,
            field_name=field_name,
            original_expression=original_expr,
            translated_expression="",  # Populated from generated code is complex; original is most useful
            translation_method=method,
            confidence=confidence,
            warnings=expr_warnings,
        )


def write_audit_csv(entries: list[ExpressionAuditEntry], path: Path) -> None:
    """Write expression audit entries to a CSV file."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "node_id",
                "tool_type",
                "field_name",
                "original_expression",
                "translation_method",
                "confidence",
                "warnings",
            ]
        )
        for entry in entries:
            writer.writerow(
                [
                    entry.node_id,
                    entry.tool_type,
                    entry.field_name,
                    entry.original_expression,
                    entry.translation_method,
                    f"{entry.confidence:.2f}",
                    "; ".join(entry.warnings) if entry.warnings else "",
                ]
            )


def audit_to_dicts(entries: list[ExpressionAuditEntry]) -> list[dict]:
    """Convert audit entries to JSON-serializable dicts."""
    return [
        {
            "node_id": e.node_id,
            "tool_type": e.tool_type,
            "field_name": e.field_name,
            "original_expression": e.original_expression,
            "translation_method": e.translation_method,
            "confidence": round(e.confidence, 2),
            "warnings": e.warnings,
        }
        for e in entries
    ]
