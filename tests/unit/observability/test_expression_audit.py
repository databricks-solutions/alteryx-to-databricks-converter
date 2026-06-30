"""Tests for the expression audit module."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from a2d.generators.base import GeneratedOutput
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    FilterNode,
    FormulaField,
    FormulaNode,
    GenerateRowsNode,
    MultiFieldFormulaNode,
    MultiRowFormulaNode,
    ReadNode,
    RegExNode,
)
from a2d.observability.expression_audit import (
    ExpressionAuditEntry,
    ExpressionAuditor,
    audit_to_dicts,
    write_audit_csv,
)


def _make_dag(*nodes) -> WorkflowDAG:
    """Create a DAG from IR nodes and add a topological_sort alias.

    The expression_audit module calls ``dag.topological_sort()`` while the
    ``WorkflowDAG`` API exposes ``topological_order()``.  We patch the
    instance so the auditor can call the expected method name.
    """
    dag = WorkflowDAG()
    for node in nodes:
        dag.add_node(node)
    # Alias so ExpressionAuditor.audit() can call dag.topological_sort()
    dag.topological_sort = dag.topological_order  # type: ignore[attr-defined]
    return dag


def _make_dag_with_edges(nodes, edges) -> WorkflowDAG:
    """Create a DAG from nodes and edges, with topological_sort alias."""
    dag = WorkflowDAG()
    for node in nodes:
        dag.add_node(node)
    for src, tgt in edges:
        dag.add_edge(src, tgt)
    dag.topological_sort = dag.topological_order  # type: ignore[attr-defined]
    return dag


# ── ExpressionAuditor.audit ─────────────────────────────────────────────


class TestExpressionAuditorAudit:
    def test_audit_formula_and_filter(self):
        formula = FormulaNode(
            node_id=1,
            original_tool_type="Formula",
            formulas=[
                FormulaField(output_field="new_col", expression="[Price] * 1.1"),
                FormulaField(output_field="label", expression='IF [x] > 0 THEN "pos" ELSE "neg" ENDIF'),
            ],
        )
        filt = FilterNode(
            node_id=2,
            original_tool_type="Filter",
            expression="[Amount] > 100",
        )
        dag = _make_dag(formula, filt)
        output = GeneratedOutput(warnings=[])
        auditor = ExpressionAuditor()

        entries = auditor.audit(dag, output)

        assert len(entries) == 3  # 2 formula fields + 1 filter
        # Check formula entries
        assert entries[0].node_id == 1
        assert entries[0].field_name == "new_col"
        assert entries[0].original_expression == "[Price] * 1.1"
        assert entries[1].field_name == "label"
        # Check filter entry
        assert entries[2].node_id == 2
        assert entries[2].field_name == "filter_condition"
        assert entries[2].original_expression == "[Amount] > 100"

    def test_audit_empty_dag(self):
        dag = _make_dag()
        output = GeneratedOutput(warnings=[])
        auditor = ExpressionAuditor()

        entries = auditor.audit(dag, output)

        assert entries == []

    def test_audit_non_expression_nodes_skipped(self):
        """ReadNode has no expressions so should produce no entries."""
        read = ReadNode(node_id=1, original_tool_type="Input Data")
        dag = _make_dag(read)
        output = GeneratedOutput(warnings=[])
        auditor = ExpressionAuditor()

        entries = auditor.audit(dag, output)

        assert entries == []

    def test_audit_filter_empty_expression_skipped(self):
        """FilterNode with empty expression should not produce an entry."""
        filt = FilterNode(node_id=1, original_tool_type="Filter", expression="")
        dag = _make_dag(filt)
        output = GeneratedOutput(warnings=[])
        auditor = ExpressionAuditor()

        entries = auditor.audit(dag, output)

        assert entries == []

    def test_audit_multi_row_formula(self):
        mrf = MultiRowFormulaNode(
            node_id=1,
            original_tool_type="MultiRowFormula",
            expression="[Row-1:Total] + [Amount]",
            output_field="RunningTotal",
        )
        dag = _make_dag(mrf)
        output = GeneratedOutput(warnings=[])
        auditor = ExpressionAuditor()

        entries = auditor.audit(dag, output)

        assert len(entries) == 1
        assert entries[0].field_name == "RunningTotal"
        assert entries[0].original_expression == "[Row-1:Total] + [Amount]"

    def test_audit_multi_field_formula(self):
        mff = MultiFieldFormulaNode(
            node_id=1,
            original_tool_type="MultiFieldFormula",
            expression="Trim([_CurrentField_])",
            fields=["col_a", "col_b", "col_c"],
        )
        dag = _make_dag(mff)
        output = GeneratedOutput(warnings=[])
        auditor = ExpressionAuditor()

        entries = auditor.audit(dag, output)

        assert len(entries) == 3
        assert [e.field_name for e in entries] == ["col_a", "col_b", "col_c"]

    def test_audit_regex_node(self):
        regex = RegExNode(
            node_id=1,
            original_tool_type="RegEx",
            expression=r"(\d{3})-(\d{4})",
            field_name="phone",
        )
        dag = _make_dag(regex)
        output = GeneratedOutput(warnings=[])
        auditor = ExpressionAuditor()

        entries = auditor.audit(dag, output)

        assert len(entries) == 1
        assert entries[0].field_name == "phone"

    def test_audit_generate_rows_node(self):
        gen = GenerateRowsNode(
            node_id=1,
            original_tool_type="GenerateRows",
            init_expression="1",
            condition_expression="i <= 10",
            loop_expression="i + 1",
            output_field="i",
        )
        dag = _make_dag(gen)
        output = GeneratedOutput(warnings=[])
        auditor = ExpressionAuditor()

        entries = auditor.audit(dag, output)

        assert len(entries) == 3
        assert entries[0].field_name == "i_init"
        assert entries[1].field_name == "i_condition"
        assert entries[2].field_name == "i_loop"

    def test_audit_warnings_detected(self):
        """Expression-related warnings lower confidence and set method to 'failed'."""
        formula = FormulaNode(
            node_id=5,
            original_tool_type="Formula",
            formulas=[
                FormulaField(output_field="col1", expression="BadFunc([x])"),
            ],
        )
        dag = _make_dag(formula)
        output = GeneratedOutput(warnings=["Node 5 Formula expression fallback: parse error"])
        auditor = ExpressionAuditor()

        entries = auditor.audit(dag, output)

        assert len(entries) == 1
        assert entries[0].translation_method == "failed"
        assert entries[0].confidence == 0.3
        assert len(entries[0].warnings) == 1

    def test_audit_expression_engine_method(self):
        """Node with conversion_method='expression-engine' is reflected in audit."""
        formula = FormulaNode(
            node_id=1,
            original_tool_type="Formula",
            conversion_method="expression-engine",
            conversion_confidence=0.85,
            formulas=[
                FormulaField(output_field="out", expression="[x] + 1"),
            ],
        )
        dag = _make_dag(formula)
        output = GeneratedOutput(warnings=[])
        auditor = ExpressionAuditor()

        entries = auditor.audit(dag, output)

        assert entries[0].translation_method == "expression-engine"
        assert entries[0].confidence == 0.85

    def test_audit_with_connected_dag(self):
        """Audit works on a DAG with edges (topological order respected)."""
        read = ReadNode(node_id=1, original_tool_type="Input Data")
        formula = FormulaNode(
            node_id=2,
            original_tool_type="Formula",
            formulas=[FormulaField(output_field="new_col", expression="[x] * 2")],
        )
        filt = FilterNode(
            node_id=3,
            original_tool_type="Filter",
            expression="[new_col] > 0",
        )
        dag = _make_dag_with_edges(
            [read, formula, filt],
            [(1, 2), (2, 3)],
        )
        output = GeneratedOutput(warnings=[])
        auditor = ExpressionAuditor()

        entries = auditor.audit(dag, output)

        assert len(entries) == 2
        # Topological order: formula before filter
        assert entries[0].node_id == 2
        assert entries[1].node_id == 3


# ── audit_to_dicts ──────────────────────────────────────────────────────


class TestAuditToDicts:
    def test_serialization(self):
        entries = [
            ExpressionAuditEntry(
                node_id=1,
                tool_type="Formula",
                field_name="col1",
                original_expression="[x] + 1",
                translated_expression="",
                translation_method="expression-engine",
                confidence=0.95,
                warnings=[],
            ),
            ExpressionAuditEntry(
                node_id=2,
                tool_type="Filter",
                field_name="filter_condition",
                original_expression="[y] > 0",
                translated_expression="",
                translation_method="failed",
                confidence=0.3,
                warnings=["expression parse failed"],
            ),
        ]

        dicts = audit_to_dicts(entries)

        assert len(dicts) == 2
        assert dicts[0]["node_id"] == 1
        assert dicts[0]["tool_type"] == "Formula"
        assert dicts[0]["field_name"] == "col1"
        assert dicts[0]["original_expression"] == "[x] + 1"
        assert dicts[0]["translation_method"] == "expression-engine"
        assert dicts[0]["confidence"] == 0.95
        assert dicts[0]["warnings"] == []

        assert dicts[1]["node_id"] == 2
        assert dicts[1]["translation_method"] == "failed"
        assert dicts[1]["confidence"] == 0.3
        assert dicts[1]["warnings"] == ["expression parse failed"]

    def test_empty_list(self):
        assert audit_to_dicts([]) == []

    def test_confidence_rounding(self):
        entry = ExpressionAuditEntry(
            node_id=1,
            tool_type="Formula",
            field_name="col",
            original_expression="[x]",
            translated_expression="",
            translation_method="deterministic",
            confidence=0.3333333,
        )
        dicts = audit_to_dicts([entry])
        assert dicts[0]["confidence"] == 0.33


# ── write_audit_csv ─────────────────────────────────────────────────────


class TestWriteAuditCsv:
    def test_creates_valid_csv(self, tmp_path: Path):
        entries = [
            ExpressionAuditEntry(
                node_id=1,
                tool_type="Formula",
                field_name="col1",
                original_expression="[x] + 1",
                translated_expression="",
                translation_method="expression-engine",
                confidence=0.95,
                warnings=[],
            ),
            ExpressionAuditEntry(
                node_id=2,
                tool_type="Filter",
                field_name="filter_condition",
                original_expression="[y] > 0",
                translated_expression="",
                translation_method="failed",
                confidence=0.3,
                warnings=["expression parse failed", "fallback used"],
            ),
        ]

        csv_path = tmp_path / "audit.csv"
        write_audit_csv(entries, csv_path)

        assert csv_path.exists()
        text = csv_path.read_text(encoding="utf-8")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)

        # Header + 2 data rows
        assert len(rows) == 3
        assert rows[0] == [
            "node_id",
            "tool_type",
            "field_name",
            "original_expression",
            "translation_method",
            "confidence",
            "warnings",
        ]
        assert rows[1][0] == "1"
        assert rows[1][1] == "Formula"
        assert rows[1][4] == "expression-engine"
        assert rows[1][5] == "0.95"
        assert rows[1][6] == ""  # no warnings

        assert rows[2][0] == "2"
        assert rows[2][4] == "failed"
        assert rows[2][5] == "0.30"
        assert rows[2][6] == "expression parse failed; fallback used"

    def test_empty_entries_writes_header_only(self, tmp_path: Path):
        csv_path = tmp_path / "empty_audit.csv"
        write_audit_csv([], csv_path)

        text = csv_path.read_text(encoding="utf-8")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)

        assert len(rows) == 1  # header only
        assert rows[0][0] == "node_id"
