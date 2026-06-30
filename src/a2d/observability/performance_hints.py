"""Performance hints — detects optimization opportunities in converted workflows.

Analyzes DAG patterns and suggests Spark-specific optimizations like
broadcast joins, caching, and repartitioning.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    AppendFieldsNode,
    JoinNode,
    LiteralDataNode,
    ReadNode,
    SummarizeNode,
)

logger = logging.getLogger("a2d.observability.performance_hints")


class HintType(Enum):
    """Performance hint categories."""

    BROADCAST_JOIN = "broadcast_join"
    CROSS_JOIN = "cross_join"
    PERSIST = "persist"
    REPARTITION = "repartition"
    COALESCE = "coalesce"
    CACHE = "cache"


class HintPriority(Enum):
    """Hint priority levels."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class PerformanceHint:
    """A single performance optimization suggestion."""

    node_id: int
    hint_type: HintType
    priority: HintPriority
    suggestion: str
    code_snippet: str = ""
    tool_type: str = ""

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "hint_type": self.hint_type.value,
            "priority": self.priority.value,
            "suggestion": self.suggestion,
            "code_snippet": self.code_snippet,
            "tool_type": self.tool_type,
        }


class PerformanceAnalyzer:
    """Detect optimization opportunities in a converted workflow DAG."""

    def analyze(self, dag: WorkflowDAG) -> list[PerformanceHint]:
        """Analyze the DAG for performance optimization opportunities."""
        hints: list[PerformanceHint] = []
        hints.extend(self._detect_broadcast_joins(dag))
        hints.extend(self._detect_cross_joins(dag))
        hints.extend(self._detect_persist_opportunities(dag))
        hints.extend(self._detect_repartition_opportunities(dag))
        hints.extend(self._detect_sequential_joins(dag))
        # Sort by priority (high first)
        priority_order = {HintPriority.HIGH: 0, HintPriority.MEDIUM: 1, HintPriority.LOW: 2}
        hints.sort(key=lambda h: priority_order[h.priority])
        return hints

    def _detect_broadcast_joins(self, dag: WorkflowDAG) -> list[PerformanceHint]:
        """Detect joins where one input is a small/lookup table (broadcast candidate)."""
        hints: list[PerformanceHint] = []
        for node in dag.all_nodes():
            if not isinstance(node, JoinNode):
                continue
            predecessors = dag.get_predecessors(node.node_id)
            for pred in predecessors:
                # LiteralDataNode = inline data, always small
                if isinstance(pred, LiteralDataNode):
                    hints.append(
                        PerformanceHint(
                            node_id=node.node_id,
                            hint_type=HintType.BROADCAST_JOIN,
                            priority=HintPriority.HIGH,
                            suggestion=(
                                f"Join at node {node.node_id} has a small literal data input "
                                f"(node {pred.node_id}). Use broadcast() for better performance."
                            ),
                            code_snippet=(
                                f"from pyspark.sql.functions import broadcast\n"
                                f"df_{node.node_id} = df_left.join(broadcast(df_{pred.node_id}), ...)"
                            ),
                            tool_type=node.original_tool_type,
                        )
                    )
                # ReadNode with no downstream fan-out = likely lookup/dimension table
                elif isinstance(pred, ReadNode) and len(dag.get_successors(pred.node_id)) == 1:
                    hints.append(
                        PerformanceHint(
                            node_id=node.node_id,
                            hint_type=HintType.BROADCAST_JOIN,
                            priority=HintPriority.MEDIUM,
                            suggestion=(
                                f"Join at node {node.node_id}: input node {pred.node_id} "
                                f"({pred.original_tool_type}) feeds only this join — likely a lookup/dimension "
                                f"table. If small (<100 MB), use broadcast() to avoid shuffle."
                            ),
                            code_snippet=(
                                f"from pyspark.sql.functions import broadcast\n"
                                f"df_{node.node_id} = df_left.join(broadcast(df_{pred.node_id}), ...)"
                            ),
                            tool_type=node.original_tool_type,
                        )
                    )
        return hints

    def _detect_cross_joins(self, dag: WorkflowDAG) -> list[PerformanceHint]:
        """Detect AppendFields nodes that produce cartesian products."""
        hints: list[PerformanceHint] = []
        for node in dag.all_nodes():
            if not isinstance(node, AppendFieldsNode):
                continue
            hints.append(
                PerformanceHint(
                    node_id=node.node_id,
                    hint_type=HintType.CROSS_JOIN,
                    priority=HintPriority.HIGH,
                    suggestion=(
                        f"AppendFields at node {node.node_id} produces a cross join (cartesian product). "
                        f"If the Source input has more than 1 row, output grows to "
                        f"Target_rows x Source_rows. Verify Source is a single-row lookup."
                    ),
                    code_snippet=(
                        "# If source is guaranteed single-row, cross join is safe.\n"
                        "# Otherwise, consider using a join with explicit keys:\n"
                        "# df = df_target.join(df_source, on='key_column', how='left')"
                    ),
                    tool_type=node.original_tool_type,
                )
            )
        return hints

    def _detect_persist_opportunities(self, dag: WorkflowDAG) -> list[PerformanceHint]:
        """Detect nodes consumed by multiple downstream nodes (persist candidates)."""
        hints: list[PerformanceHint] = []
        for node in dag.all_nodes():
            successors = dag.get_successors(node.node_id)
            if len(successors) > 1:
                hints.append(
                    PerformanceHint(
                        node_id=node.node_id,
                        hint_type=HintType.PERSIST,
                        priority=HintPriority.MEDIUM,
                        suggestion=(
                            f"Node {node.node_id} ({node.original_tool_type}) feeds into "
                            f"{len(successors)} downstream nodes. Consider persisting/caching "
                            f"to avoid recomputation."
                        ),
                        code_snippet=f"df_{node.node_id} = df_{node.node_id}.persist()",
                        tool_type=node.original_tool_type,
                    )
                )
        return hints

    def _detect_repartition_opportunities(self, dag: WorkflowDAG) -> list[PerformanceHint]:
        """Detect SummarizeNodes with many group-by fields (repartition candidates)."""
        hints: list[PerformanceHint] = []
        for node in dag.all_nodes():
            if not isinstance(node, SummarizeNode):
                continue
            group_by_count = sum(1 for agg in node.aggregations if agg.action.value == "GroupBy")
            if group_by_count >= 3:
                hints.append(
                    PerformanceHint(
                        node_id=node.node_id,
                        hint_type=HintType.REPARTITION,
                        priority=HintPriority.MEDIUM,
                        suggestion=(
                            f"Summarize at node {node.node_id} groups by {group_by_count} fields. "
                            f"Consider repartitioning by group-by columns before aggregation."
                        ),
                        code_snippet="df = df.repartition('group_col1', 'group_col2', ...)",
                        tool_type=node.original_tool_type,
                    )
                )
        return hints

    def _detect_sequential_joins(self, dag: WorkflowDAG) -> list[PerformanceHint]:
        """Detect chains of sequential joins (coalesce candidate)."""
        hints: list[PerformanceHint] = []
        seen_chains: set[int] = set()

        for node in dag.all_nodes():
            if not isinstance(node, JoinNode) or node.node_id in seen_chains:
                continue
            # Walk downstream to find chain of joins
            chain_length = 1
            current = node
            while True:
                successors = dag.get_successors(current.node_id)
                join_successors = [s for s in successors if isinstance(s, JoinNode)]
                if not join_successors:
                    break
                current = join_successors[0]
                seen_chains.add(current.node_id)
                chain_length += 1

            if chain_length >= 3:
                hints.append(
                    PerformanceHint(
                        node_id=node.node_id,
                        hint_type=HintType.COALESCE,
                        priority=HintPriority.LOW,
                        suggestion=(
                            f"Chain of {chain_length} sequential joins starting at node {node.node_id}. "
                            f"Consider adding a coalesce or checkpoint between joins to control partitioning."
                        ),
                        code_snippet="df = df.coalesce(num_partitions)  # or df.checkpoint()",
                        tool_type=node.original_tool_type,
                    )
                )
        return hints


def hints_to_dicts(hints: list[PerformanceHint]) -> list[dict]:
    """Convert performance hints to JSON-serializable dicts."""
    return [h.to_dict() for h in hints]
