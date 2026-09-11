"""Tool coverage analysis for migration readiness assessment."""

from __future__ import annotations

from dataclasses import dataclass, field

from a2d.converters.registry import ConverterRegistry
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import UnsupportedNode


@dataclass
class CoverageReport:
    """Coverage analysis showing supported vs unsupported tools."""

    total_nodes: int
    unique_tool_types: set[str]
    supported_types: set[str]
    unsupported_types: set[str]
    coverage_percentage: float
    per_tool_counts: dict[str, int] = field(default_factory=dict)
    # Instance-weighted coverage: the share of tool INSTANCES (not distinct types)
    # that are supported. The type-based `coverage_percentage` above treats one
    # unsupported type the same whether it appears once or 1,000 times; this gives
    # the complementary node-weighted view. Neither measures semantic correctness
    # of the generated code — a supported type can still emit a caveated result.
    instance_coverage_percentage: float = 100.0


class CoverageAnalyzer:
    """Analyze tool coverage for a workflow DAG."""

    def analyze_dag(self, dag: WorkflowDAG) -> CoverageReport:
        """Analyze which tools are supported and their frequency."""
        total_nodes = dag.node_count
        unique_tool_types: set[str] = set()
        per_tool_counts: dict[str, int] = {}

        for node in dag.all_nodes():
            tool_type = node.original_tool_type or type(node).__name__.replace("Node", "")
            unique_tool_types.add(tool_type)
            per_tool_counts[tool_type] = per_tool_counts.get(tool_type, 0) + 1

        supported_registry = ConverterRegistry.supported_tools()
        supported_types = unique_tool_types & supported_registry
        unsupported_types = unique_tool_types - supported_registry

        # Also count nodes that converted to UnsupportedNode
        for node in dag.all_nodes():
            if isinstance(node, UnsupportedNode):
                tool_type = node.original_tool_type or "Unknown"
                unsupported_types.add(tool_type)
                supported_types.discard(tool_type)

        coverage_percentage = len(supported_types) / len(unique_tool_types) * 100.0 if unique_tool_types else 100.0

        # Instance-weighted: share of tool instances whose type is supported.
        supported_instances = sum(c for t, c in per_tool_counts.items() if t in supported_types)
        instance_coverage = supported_instances / total_nodes * 100.0 if total_nodes else 100.0

        return CoverageReport(
            total_nodes=total_nodes,
            unique_tool_types=unique_tool_types,
            supported_types=supported_types,
            unsupported_types=unsupported_types,
            coverage_percentage=round(coverage_percentage, 1),
            per_tool_counts=per_tool_counts,
            instance_coverage_percentage=round(instance_coverage, 1),
        )
