"""Migration readiness assessment combining complexity and coverage analysis."""

from __future__ import annotations

from dataclasses import dataclass, field

from a2d.analyzer.complexity import ComplexityScore
from a2d.analyzer.coverage import CoverageReport


@dataclass
class WorkflowAnalysis:
    """Complete analysis of a single workflow."""

    file_path: str
    workflow_name: str
    complexity: ComplexityScore
    coverage: CoverageReport
    node_count: int
    connection_count: int
    tool_types_used: set[str]
    warnings: list[str] = field(default_factory=list)
    migration_priority: str = "Medium"  # Low, Medium, High
    estimated_effort: str = "Medium"  # Low, Medium, High


class ReadinessAssessor:
    """Assess migration priority and effort based on complexity and coverage."""

    def assess(self, complexity: ComplexityScore, coverage: CoverageReport) -> tuple[str, str]:
        """Return (migration_priority, estimated_effort).

        Priority logic:
            - High coverage + low complexity = High priority (easy wins)
            - Medium coverage + medium complexity = Medium priority
            - Low coverage + high complexity = Low priority (hard)

        Effort logic:
            - Based on complexity level and coverage percentage.
        """
        cov_pct = coverage.coverage_percentage
        complexity_score = complexity.total_score

        # Determine migration priority
        # High priority = easy wins (high coverage, low complexity)
        if (cov_pct >= 80 and complexity_score < 30) or (cov_pct >= 60 and complexity_score < 50):
            priority = "High"
        elif cov_pct >= 40 and complexity_score < 60:
            priority = "Medium"
        elif cov_pct < 40 or complexity_score >= 70:
            priority = "Low"
        else:
            priority = "Medium"

        # Determine estimated effort
        if complexity_score < 25 and cov_pct >= 80:
            effort = "Low"
        elif (complexity_score < 50 and cov_pct >= 50) or complexity_score < 75:
            effort = "Medium"
        else:
            effort = "High"

        return priority, effort
