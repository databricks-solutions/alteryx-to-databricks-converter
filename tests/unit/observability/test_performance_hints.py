"""Tests for the performance hints module."""

from __future__ import annotations

from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    AggAction,
    AggregationField,
    FilterNode,
    FormulaNode,
    JoinNode,
    LiteralDataNode,
    ReadNode,
    SummarizeNode,
)
from a2d.observability.performance_hints import (
    HintPriority,
    HintType,
    PerformanceAnalyzer,
    PerformanceHint,
    hints_to_dicts,
)


def _make_dag_with_edges(nodes, edges) -> WorkflowDAG:
    """Create a DAG from nodes and directed edges."""
    dag = WorkflowDAG()
    for node in nodes:
        dag.add_node(node)
    for src, tgt in edges:
        dag.add_edge(src, tgt)
    return dag


# ── Broadcast join detection ────────────────────────────────────────────


class TestBroadcastJoinDetection:
    def test_literal_data_into_join(self):
        """A LiteralDataNode feeding into a JoinNode should trigger a HIGH broadcast hint.
        A ReadNode with a single successor also triggers a MEDIUM hint."""
        literal = LiteralDataNode(node_id=1, original_tool_type="TextInput", num_records=5)
        read = ReadNode(node_id=2, original_tool_type="Input Data")
        join = JoinNode(node_id=3, original_tool_type="Join")

        dag = _make_dag_with_edges(
            [literal, read, join],
            [(1, 3), (2, 3)],
        )

        analyzer = PerformanceAnalyzer()
        hints = analyzer.analyze(dag)

        broadcast_hints = [h for h in hints if h.hint_type == HintType.BROADCAST_JOIN]
        assert len(broadcast_hints) == 2
        high_hints = [h for h in broadcast_hints if h.priority == HintPriority.HIGH]
        medium_hints = [h for h in broadcast_hints if h.priority == HintPriority.MEDIUM]
        assert len(high_hints) == 1
        assert high_hints[0].node_id == 3
        assert "broadcast" in high_hints[0].suggestion.lower()
        assert str(literal.node_id) in high_hints[0].suggestion
        # ReadNode with single successor also flagged as lookup candidate
        assert len(medium_hints) == 1
        assert str(read.node_id) in medium_hints[0].suggestion

    def test_read_node_single_successor_broadcast_hint(self):
        """A ReadNode feeding only into one JoinNode triggers a MEDIUM broadcast hint."""
        read1 = ReadNode(node_id=1, original_tool_type="Input Data")
        read2 = ReadNode(node_id=2, original_tool_type="Input Data")
        join = JoinNode(node_id=3, original_tool_type="Join")

        dag = _make_dag_with_edges(
            [read1, read2, join],
            [(1, 3), (2, 3)],
        )

        analyzer = PerformanceAnalyzer()
        hints = analyzer.analyze(dag)

        broadcast_hints = [h for h in hints if h.hint_type == HintType.BROADCAST_JOIN]
        # Both ReadNodes have a single successor → both flagged as potential lookups
        assert len(broadcast_hints) == 2
        assert all(h.priority == HintPriority.MEDIUM for h in broadcast_hints)

    def test_read_node_multiple_successors_no_broadcast_hint(self):
        """ReadNodes feeding into multiple downstream nodes should not trigger broadcast hint."""
        read1 = ReadNode(node_id=1, original_tool_type="Input Data")
        read2 = ReadNode(node_id=2, original_tool_type="Input Data")
        join = JoinNode(node_id=3, original_tool_type="Join")
        formula = FormulaNode(node_id=4, original_tool_type="Formula")

        dag = _make_dag_with_edges(
            [read1, read2, join, formula],
            [(1, 3), (1, 4), (2, 3), (2, 4)],  # Both reads have 2 successors
        )

        analyzer = PerformanceAnalyzer()
        hints = analyzer.analyze(dag)

        broadcast_hints = [h for h in hints if h.hint_type == HintType.BROADCAST_JOIN]
        assert broadcast_hints == []


# ── Persist detection ───────────────────────────────────────────────────


class TestPersistDetection:
    def test_node_with_multiple_successors(self):
        """A node feeding into 2+ downstream nodes should trigger a persist hint."""
        read = ReadNode(node_id=1, original_tool_type="Input Data")
        formula1 = FormulaNode(node_id=2, original_tool_type="Formula")
        formula2 = FormulaNode(node_id=3, original_tool_type="Formula")

        dag = _make_dag_with_edges(
            [read, formula1, formula2],
            [(1, 2), (1, 3)],
        )

        analyzer = PerformanceAnalyzer()
        hints = analyzer.analyze(dag)

        persist_hints = [h for h in hints if h.hint_type == HintType.PERSIST]
        assert len(persist_hints) == 1
        assert persist_hints[0].node_id == 1
        assert persist_hints[0].priority == HintPriority.MEDIUM
        assert "persist" in persist_hints[0].suggestion.lower() or "caching" in persist_hints[0].suggestion.lower()

    def test_node_with_single_successor_no_hint(self):
        """A linear pipeline should not trigger persist hints."""
        read = ReadNode(node_id=1, original_tool_type="Input Data")
        formula = FormulaNode(node_id=2, original_tool_type="Formula")

        dag = _make_dag_with_edges(
            [read, formula],
            [(1, 2)],
        )

        analyzer = PerformanceAnalyzer()
        hints = analyzer.analyze(dag)

        persist_hints = [h for h in hints if h.hint_type == HintType.PERSIST]
        assert persist_hints == []

    def test_node_with_three_successors(self):
        """A node feeding into 3 downstream nodes should still trigger a persist hint."""
        read = ReadNode(node_id=1, original_tool_type="Input Data")
        f1 = FormulaNode(node_id=2, original_tool_type="Formula")
        f2 = FormulaNode(node_id=3, original_tool_type="Formula")
        f3 = FilterNode(node_id=4, original_tool_type="Filter", expression="[x] > 0")

        dag = _make_dag_with_edges(
            [read, f1, f2, f3],
            [(1, 2), (1, 3), (1, 4)],
        )

        analyzer = PerformanceAnalyzer()
        hints = analyzer.analyze(dag)

        persist_hints = [h for h in hints if h.hint_type == HintType.PERSIST]
        assert len(persist_hints) == 1
        assert "3" in persist_hints[0].suggestion  # mentions "3 downstream nodes"


# ── Repartition detection ──────────────────────────────────────────────


class TestRepartitionDetection:
    def test_summarize_with_many_group_by_fields(self):
        """SummarizeNode with >= 3 GroupBy fields should trigger repartition hint."""
        summarize = SummarizeNode(
            node_id=1,
            original_tool_type="Summarize",
            aggregations=[
                AggregationField(field_name="region", action=AggAction.GROUP_BY),
                AggregationField(field_name="product", action=AggAction.GROUP_BY),
                AggregationField(field_name="year", action=AggAction.GROUP_BY),
                AggregationField(field_name="revenue", action=AggAction.SUM),
            ],
        )
        dag = WorkflowDAG()
        dag.add_node(summarize)

        analyzer = PerformanceAnalyzer()
        hints = analyzer.analyze(dag)

        repartition_hints = [h for h in hints if h.hint_type == HintType.REPARTITION]
        assert len(repartition_hints) == 1
        assert repartition_hints[0].node_id == 1
        assert "3" in repartition_hints[0].suggestion
        assert "repartition" in repartition_hints[0].suggestion.lower()

    def test_summarize_with_few_group_by_fields(self):
        """SummarizeNode with < 3 GroupBy fields should not trigger repartition hint."""
        summarize = SummarizeNode(
            node_id=1,
            original_tool_type="Summarize",
            aggregations=[
                AggregationField(field_name="region", action=AggAction.GROUP_BY),
                AggregationField(field_name="revenue", action=AggAction.SUM),
            ],
        )
        dag = WorkflowDAG()
        dag.add_node(summarize)

        analyzer = PerformanceAnalyzer()
        hints = analyzer.analyze(dag)

        repartition_hints = [h for h in hints if h.hint_type == HintType.REPARTITION]
        assert repartition_hints == []

    def test_summarize_with_exactly_three_group_by(self):
        """Boundary case: exactly 3 GroupBy fields triggers the hint."""
        summarize = SummarizeNode(
            node_id=1,
            original_tool_type="Summarize",
            aggregations=[
                AggregationField(field_name="a", action=AggAction.GROUP_BY),
                AggregationField(field_name="b", action=AggAction.GROUP_BY),
                AggregationField(field_name="c", action=AggAction.GROUP_BY),
            ],
        )
        dag = WorkflowDAG()
        dag.add_node(summarize)

        analyzer = PerformanceAnalyzer()
        hints = analyzer.analyze(dag)

        repartition_hints = [h for h in hints if h.hint_type == HintType.REPARTITION]
        assert len(repartition_hints) == 1

    def test_summarize_with_two_group_by_no_hint(self):
        """Boundary case: 2 GroupBy fields does not trigger the hint."""
        summarize = SummarizeNode(
            node_id=1,
            original_tool_type="Summarize",
            aggregations=[
                AggregationField(field_name="a", action=AggAction.GROUP_BY),
                AggregationField(field_name="b", action=AggAction.GROUP_BY),
            ],
        )
        dag = WorkflowDAG()
        dag.add_node(summarize)

        analyzer = PerformanceAnalyzer()
        hints = analyzer.analyze(dag)

        repartition_hints = [h for h in hints if h.hint_type == HintType.REPARTITION]
        assert repartition_hints == []


# ── Sequential joins detection ──────────────────────────────────────────


class TestSequentialJoinsDetection:
    def test_chain_of_three_joins(self):
        """A chain of 3 sequential joins should trigger a coalesce hint."""
        read1 = ReadNode(node_id=1, original_tool_type="Input Data")
        read2 = ReadNode(node_id=2, original_tool_type="Input Data")
        read3 = ReadNode(node_id=3, original_tool_type="Input Data")
        read4 = ReadNode(node_id=4, original_tool_type="Input Data")
        join1 = JoinNode(node_id=10, original_tool_type="Join")
        join2 = JoinNode(node_id=11, original_tool_type="Join")
        join3 = JoinNode(node_id=12, original_tool_type="Join")

        dag = _make_dag_with_edges(
            [read1, read2, read3, read4, join1, join2, join3],
            [
                (1, 10),
                (2, 10),  # join1: read1 + read2
                (10, 11),
                (3, 11),  # join2: join1 + read3
                (11, 12),
                (4, 12),  # join3: join2 + read4
            ],
        )

        analyzer = PerformanceAnalyzer()
        hints = analyzer.analyze(dag)

        coalesce_hints = [h for h in hints if h.hint_type == HintType.COALESCE]
        assert len(coalesce_hints) == 1
        assert coalesce_hints[0].node_id == 10  # start of chain
        assert "3" in coalesce_hints[0].suggestion
        assert coalesce_hints[0].priority == HintPriority.LOW

    def test_two_joins_no_hint(self):
        """Only 2 sequential joins should not trigger the coalesce hint (threshold is 3)."""
        read1 = ReadNode(node_id=1, original_tool_type="Input Data")
        read2 = ReadNode(node_id=2, original_tool_type="Input Data")
        read3 = ReadNode(node_id=3, original_tool_type="Input Data")
        join1 = JoinNode(node_id=10, original_tool_type="Join")
        join2 = JoinNode(node_id=11, original_tool_type="Join")

        dag = _make_dag_with_edges(
            [read1, read2, read3, join1, join2],
            [
                (1, 10),
                (2, 10),
                (10, 11),
                (3, 11),
            ],
        )

        analyzer = PerformanceAnalyzer()
        hints = analyzer.analyze(dag)

        coalesce_hints = [h for h in hints if h.hint_type == HintType.COALESCE]
        assert coalesce_hints == []

    def test_isolated_joins_no_chain(self):
        """Two independent joins (not chained) should not trigger coalesce."""
        read1 = ReadNode(node_id=1, original_tool_type="Input Data")
        read2 = ReadNode(node_id=2, original_tool_type="Input Data")
        read3 = ReadNode(node_id=3, original_tool_type="Input Data")
        read4 = ReadNode(node_id=4, original_tool_type="Input Data")
        join1 = JoinNode(node_id=10, original_tool_type="Join")
        join2 = JoinNode(node_id=11, original_tool_type="Join")

        dag = _make_dag_with_edges(
            [read1, read2, read3, read4, join1, join2],
            [
                (1, 10),
                (2, 10),  # join1
                (3, 11),
                (4, 11),  # join2 (independent)
            ],
        )

        analyzer = PerformanceAnalyzer()
        hints = analyzer.analyze(dag)

        coalesce_hints = [h for h in hints if h.hint_type == HintType.COALESCE]
        assert coalesce_hints == []


# ── Empty DAG ───────────────────────────────────────────────────────────


class TestEmptyDag:
    def test_empty_dag_returns_empty_hints(self):
        dag = WorkflowDAG()
        analyzer = PerformanceAnalyzer()
        hints = analyzer.analyze(dag)
        assert hints == []


# ── hints_to_dicts serialization ────────────────────────────────────────


class TestHintsToDicts:
    def test_serialization(self):
        hints = [
            PerformanceHint(
                node_id=5,
                hint_type=HintType.BROADCAST_JOIN,
                priority=HintPriority.HIGH,
                suggestion="Use broadcast join",
                code_snippet="broadcast(df)",
                tool_type="Join",
            ),
            PerformanceHint(
                node_id=10,
                hint_type=HintType.PERSIST,
                priority=HintPriority.MEDIUM,
                suggestion="Consider persisting",
                tool_type="Formula",
            ),
        ]

        dicts = hints_to_dicts(hints)

        assert len(dicts) == 2
        assert dicts[0]["node_id"] == 5
        assert dicts[0]["hint_type"] == "broadcast_join"
        assert dicts[0]["priority"] == "high"
        assert dicts[0]["suggestion"] == "Use broadcast join"
        assert dicts[0]["code_snippet"] == "broadcast(df)"
        assert dicts[0]["tool_type"] == "Join"

        assert dicts[1]["node_id"] == 10
        assert dicts[1]["hint_type"] == "persist"
        assert dicts[1]["priority"] == "medium"

    def test_empty_list(self):
        assert hints_to_dicts([]) == []

    def test_to_dict_code_snippet_default(self):
        """PerformanceHint.to_dict includes empty code_snippet by default."""
        hint = PerformanceHint(
            node_id=1,
            hint_type=HintType.CACHE,
            priority=HintPriority.LOW,
            suggestion="Cache this",
        )
        d = hint.to_dict()
        assert d["code_snippet"] == ""
        assert d["tool_type"] == ""


# ── Priority sorting ────────────────────────────────────────────────────


class TestPrioritySorting:
    def test_hints_sorted_by_priority(self):
        """analyze() should return hints sorted: HIGH first, then MEDIUM, then LOW."""
        # Build a DAG that triggers multiple hint types
        literal = LiteralDataNode(node_id=1, original_tool_type="TextInput")
        read = ReadNode(node_id=2, original_tool_type="Input Data")
        join = JoinNode(node_id=3, original_tool_type="Join")
        summarize = SummarizeNode(
            node_id=4,
            original_tool_type="Summarize",
            aggregations=[
                AggregationField(field_name="a", action=AggAction.GROUP_BY),
                AggregationField(field_name="b", action=AggAction.GROUP_BY),
                AggregationField(field_name="c", action=AggAction.GROUP_BY),
            ],
        )

        dag = _make_dag_with_edges(
            [literal, read, join, summarize],
            [(1, 3), (2, 3), (3, 4)],
        )

        analyzer = PerformanceAnalyzer()
        hints = analyzer.analyze(dag)

        # We should have at least a broadcast (HIGH) and repartition (MEDIUM)
        priorities = [h.priority for h in hints]
        priority_order = {HintPriority.HIGH: 0, HintPriority.MEDIUM: 1, HintPriority.LOW: 2}
        order_values = [priority_order[p] for p in priorities]
        assert order_values == sorted(order_values), "Hints should be sorted by priority (HIGH first)"
