"""Conversion confidence scoring — deterministic 0-100 score per workflow."""

from __future__ import annotations

from dataclasses import dataclass, field

from a2d.generators.base import GeneratedOutput
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    JoinNode,
    SelectNode,
    UnsupportedNode,
)


@dataclass
class ConfidenceDimension:
    """A single scored dimension contributing to the overall confidence."""

    name: str
    score: float  # 0-100
    weight: float  # contribution to overall (sums to 1.0)
    details: str  # human-readable explanation


@dataclass
class ConfidenceScore:
    """Composite confidence score for a converted workflow."""

    overall: float  # 0-100 weighted composite
    level: str  # "High", "Medium", "Low"
    dimensions: list[ConfidenceDimension] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize for JSON output."""
        return {
            "overall": round(self.overall, 1),
            "level": self.level,
            "dimensions": [
                {
                    "name": d.name,
                    "score": round(d.score, 1),
                    "weight": d.weight,
                    "details": d.details,
                }
                for d in self.dimensions
            ],
        }


class ConfidenceScorer:
    """Score conversion confidence from DAG and generation output.

    Dimensions (weights sum to 1.0):
        1. Tool coverage (0.35) — % of nodes with a real converter
        2. Expression fidelity (0.25) — % of warnings not expression-related
        3. Join completeness (0.15) — % of joins with resolved keys
        4. Data type preservation (0.15) — % of SelectNodes with field mappings
        5. Generator warnings (0.10) — inverse of warning density
    """

    def score(self, dag: WorkflowDAG, output: GeneratedOutput) -> ConfidenceScore:
        """Compute a confidence score from the conversion artifacts."""
        dims = [
            self._score_tool_coverage(dag),
            self._score_expression_fidelity(output),
            self._score_join_completeness(dag),
            self._score_data_type_preservation(dag),
            self._score_generator_warnings(dag, output),
        ]
        assert abs(sum(d.weight for d in dims) - 1.0) < 0.001, "Confidence weights must sum to 1.0"

        overall = sum(d.score * d.weight for d in dims)
        overall = max(0.0, min(100.0, overall))

        if overall >= 80:
            level = "High"
        elif overall >= 50:
            level = "Medium"
        else:
            level = "Low"

        return ConfidenceScore(overall=overall, level=level, dimensions=dims)

    # ── Dimension scorers ─────────────────────────────────────────────

    @staticmethod
    def _score_tool_coverage(dag: WorkflowDAG) -> ConfidenceDimension:
        """Ratio of supported nodes to total nodes."""
        total = 0
        unsupported = 0
        for node in dag.all_nodes():
            total += 1
            if isinstance(node, UnsupportedNode):
                unsupported += 1

        score = 100.0 if total == 0 else (total - unsupported) / total * 100.0

        return ConfidenceDimension(
            name="tool_coverage",
            score=score,
            weight=0.35,
            details=f"{total - unsupported}/{total} nodes have converters",
        )

    @staticmethod
    def _score_expression_fidelity(output: GeneratedOutput) -> ConfidenceDimension:
        """Ratio of warnings that are NOT expression-related."""
        total_warnings = len(output.warnings)
        if total_warnings == 0:
            return ConfidenceDimension(
                name="expression_fidelity",
                score=100.0,
                weight=0.25,
                details="No expression warnings",
            )

        expr_keywords = ("expression", "formula", "parse fail", "placeholder", "fallback")
        expr_warnings = sum(1 for w in output.warnings if any(k in w.lower() for k in expr_keywords))

        score = max(0.0, (1.0 - expr_warnings / total_warnings) * 100.0)

        return ConfidenceDimension(
            name="expression_fidelity",
            score=score,
            weight=0.25,
            details=f"{total_warnings - expr_warnings}/{total_warnings} warnings are non-expression",
        )

    @staticmethod
    def _score_join_completeness(dag: WorkflowDAG) -> ConfidenceDimension:
        """Ratio of JoinNodes with resolved keys (not F.lit(True))."""
        total_joins = 0
        resolved_joins = 0
        for node in dag.all_nodes():
            if isinstance(node, JoinNode):
                total_joins += 1
                if node.join_keys:
                    resolved_joins += 1

        if total_joins == 0:
            return ConfidenceDimension(
                name="join_completeness",
                score=100.0,
                weight=0.15,
                details="No joins in workflow",
            )

        score = (resolved_joins / total_joins) * 100.0
        return ConfidenceDimension(
            name="join_completeness",
            score=score,
            weight=0.15,
            details=f"{resolved_joins}/{total_joins} joins have resolved keys",
        )

    @staticmethod
    def _score_data_type_preservation(dag: WorkflowDAG) -> ConfidenceDimension:
        """Ratio of SelectNodes that actually define field operations."""
        total_selects = 0
        selects_with_fields = 0
        for node in dag.all_nodes():
            if isinstance(node, SelectNode):
                total_selects += 1
                if node.field_operations:
                    selects_with_fields += 1

        if total_selects == 0:
            return ConfidenceDimension(
                name="data_type_preservation",
                score=100.0,
                weight=0.15,
                details="No select nodes in workflow",
            )

        score = (selects_with_fields / total_selects) * 100.0
        return ConfidenceDimension(
            name="data_type_preservation",
            score=score,
            weight=0.15,
            details=f"{selects_with_fields}/{total_selects} selects have field mappings",
        )

    @staticmethod
    def _score_generator_warnings(dag: WorkflowDAG, output: GeneratedOutput) -> ConfidenceDimension:
        """Inverse of warning density (warnings per node)."""
        node_count = dag.node_count
        warning_count = len(output.warnings)

        if node_count == 0:
            score = 100.0
        else:
            density = warning_count / node_count
            # 0 warnings = 100, 1 warning/node = 0
            score = max(0.0, (1.0 - density) * 100.0)

        return ConfidenceDimension(
            name="generator_warnings",
            score=score,
            weight=0.10,
            details=f"{warning_count} warnings across {node_count} nodes",
        )
