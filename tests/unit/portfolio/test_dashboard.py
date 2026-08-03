"""Tests for the executive migration dashboard."""

from __future__ import annotations

from pathlib import Path

from a2d.analyzer.complexity import ComplexityScore
from a2d.analyzer.coverage import CoverageReport
from a2d.analyzer.readiness import WorkflowAnalysis
from a2d.portfolio.analyzer import PortfolioAnalyzer
from a2d.portfolio.dashboard import build_rollup, generate_dashboard, risk_tier

PORTFOLIO_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "portfolio"


def _analysis(name, *, coverage, complexity):
    return WorkflowAnalysis(
        file_path=f"{name}.yxmd",
        workflow_name=name,
        complexity=ComplexityScore(
            total_score=complexity,
            level="Low" if complexity < 25 else "High",
            node_count=5,
            edge_count=4,
            unique_tool_types=3,
            unsupported_count=0,
            expression_count=0,
            max_dag_depth=2,
            has_macro_refs=False,
        ),
        coverage=CoverageReport(
            total_nodes=5,
            unique_tool_types={"A", "B"},
            supported_types={"A"},
            unsupported_types={"B"},
            coverage_percentage=coverage,
        ),
        node_count=5,
        connection_count=4,
        tool_types_used={"A", "B"},
    )


class TestRiskTier:
    def test_ready(self):
        assert risk_tier(_analysis("w", coverage=95.0, complexity=20.0)) == "ready"

    def test_high_risk_low_coverage(self):
        assert risk_tier(_analysis("w", coverage=50.0, complexity=10.0)) == "high_risk"

    def test_high_risk_high_complexity(self):
        assert risk_tier(_analysis("w", coverage=100.0, complexity=80.0)) == "high_risk"

    def test_needs_review_middle(self):
        assert risk_tier(_analysis("w", coverage=80.0, complexity=60.0)) == "needs_review"


class TestRollup:
    def _report(self):
        return PortfolioAnalyzer().analyze(sorted(PORTFOLIO_FIXTURES.glob("*.yxmd")))

    def test_rollup_counts(self):
        roll = build_rollup(self._report())
        assert roll.workflow_count == 3
        assert roll.ready_count + roll.review_count + roll.high_risk_count == 3

    def test_reuse_savings_from_shared_assets(self):
        # The portfolio fixtures share 1 macro (2 uses) and 1 sub-flow (2 copies):
        # savings = (2-1) + (2-1) = 2 days.
        roll = build_rollup(self._report())
        assert roll.reuse_savings_days == 2.0

    def test_effort_matches_plan(self):
        report = self._report()
        roll = build_rollup(report)
        assert roll.total_effort_days == round(report.plan.total_effort_days, 1)


class TestDashboardHtml:
    def test_written_and_has_sections(self, tmp_path):
        report = PortfolioAnalyzer().analyze(sorted(PORTFOLIO_FIXTURES.glob("*.yxmd")))
        out = tmp_path / "dash.html"
        generate_dashboard(report, out)
        html = out.read_text()
        assert "<!DOCTYPE html>" in html
        assert "Executive Migration Dashboard" in html
        assert "Migration Readiness" in html
        assert "Top Migration Blockers" in html
        assert "Consolidation Opportunities" in html

    def test_empty_estate(self, tmp_path):
        report = PortfolioAnalyzer().analyze([])
        out = tmp_path / "dash.html"
        generate_dashboard(report, out)  # must not crash on zero workflows
        assert out.exists()
