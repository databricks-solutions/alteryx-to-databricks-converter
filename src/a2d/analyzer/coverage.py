"""Tool coverage analysis for migration readiness assessment."""

from __future__ import annotations

from dataclasses import dataclass, field

from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import CommentNode, UnsupportedNode
from a2d.macro.detect import macro_file_name, macro_path_for_ir_node


@dataclass
class CoverageReport:
    """Coverage analysis showing supported vs unsupported tools.

    ``coverage_percentage`` is THE coverage figure everywhere in a2d: the share of
    the workflow's tools (every node except canvas comments) that the converter
    handles, i.e. that didn't fall back to an unsupported placeholder. It is the
    same count every code generator reports as ``supported_nodes / total_nodes``,
    so Assess (before converting) and Convert (after) show the same number for the
    same workflow. It says nothing about semantic correctness: a supported tool
    can still emit a caveated result.

    ``type_coverage_percentage`` is the share of distinct tool *types* that are
    supported. It is a different question (one unsupported type counts the same
    whether it appears once or 1,000 times) and is labelled as such where shown.
    """

    total_nodes: int  # tools counted for coverage (canvas comments excluded)
    unique_tool_types: set[str]
    supported_types: set[str]
    unsupported_types: set[str]
    coverage_percentage: float
    per_tool_counts: dict[str, int] = field(default_factory=dict)
    type_coverage_percentage: float = 100.0
    supported_nodes: int = 0
    # Macro calls left unexpanded (file missing, batch/iterative, ...), by macro
    # file name -> why. They count as unconverted tools in the percentage, but are
    # named here instead of showing up as an unsupported "Macro" tool type.
    unresolved_macros: dict[str, str] = field(default_factory=dict)

    @property
    def instance_coverage_percentage(self) -> float:
        """Alias kept for callers written before the two figures were unified."""
        return self.coverage_percentage


def tool_nodes(dag: WorkflowDAG) -> list:
    """The nodes coverage counts: every node except canvas comments."""
    return [n for n in dag.all_nodes() if not isinstance(n, CommentNode)]


class CoverageAnalyzer:
    """Analyze tool coverage for a workflow DAG."""

    def analyze_dag(self, dag: WorkflowDAG) -> CoverageReport:
        """Analyze which tools are supported and their frequency."""
        tools = tool_nodes(dag)
        total_nodes = len(tools)
        unique_tool_types: set[str] = set()
        per_tool_counts: dict[str, int] = {}
        unsupported_types: set[str] = set()
        unresolved_macros: dict[str, str] = {}
        supported_nodes = 0

        for node in tools:
            tool_type = node.original_tool_type or type(node).__name__.replace("Node", "")
            per_tool_counts[tool_type] = per_tool_counts.get(tool_type, 0) + 1
            macro_path = macro_path_for_ir_node(node) if isinstance(node, UnsupportedNode) else None
            if macro_path:
                name = macro_file_name(macro_path)
                # The reason is shown next to the name, so drop the engine's "Macro <name> wasn't expanded:" lead-in.
                reason = (node.unsupported_reason or "").removeprefix(f"Macro {name} wasn't expanded: ").strip()
                unresolved_macros.setdefault(name, reason[:1].upper() + reason[1:])
                continue
            unique_tool_types.add(tool_type)
            if isinstance(node, UnsupportedNode):
                unsupported_types.add(node.original_tool_type or "Unknown")
            else:
                supported_nodes += 1

        # A type is supported when none of its instances fell back to an
        # unsupported placeholder: what the converter actually did, so the type
        # list and the percentage can't disagree.
        supported_types = unique_tool_types - unsupported_types

        coverage = supported_nodes / total_nodes * 100.0 if total_nodes else 100.0
        type_coverage = len(supported_types) / len(unique_tool_types) * 100.0 if unique_tool_types else 100.0

        return CoverageReport(
            total_nodes=total_nodes,
            unique_tool_types=unique_tool_types,
            supported_types=supported_types,
            unsupported_types=unsupported_types,
            coverage_percentage=round(coverage, 1),
            per_tool_counts=per_tool_counts,
            type_coverage_percentage=round(type_coverage, 1),
            supported_nodes=supported_nodes,
            unresolved_macros=dict(sorted(unresolved_macros.items())),
        )


def estate_coverage_percentage(reports: list[CoverageReport]) -> float:
    """Coverage across several workflows: supported tools over all tools, so a
    2-tool and a 200-tool workflow don't count equally. 100.0 when there are none."""
    total = sum(r.total_nodes for r in reports)
    return round(sum(r.supported_nodes for r in reports) / total * 100.0, 1) if total else 100.0
