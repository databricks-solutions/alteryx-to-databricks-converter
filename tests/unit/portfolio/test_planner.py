"""Tests for the migration-wave planner."""

from __future__ import annotations

from a2d.analyzer.complexity import ComplexityScore
from a2d.analyzer.coverage import CoverageReport
from a2d.analyzer.readiness import WorkflowAnalysis
from a2d.portfolio.models import ArtifactDependency, _effort_days
from a2d.portfolio.planner import MigrationWavePlanner, days_for_effort


def _analysis(name, *, nodes=10, coverage=100.0, complexity=10.0, effort="Low"):
    return WorkflowAnalysis(
        file_path=f"{name}.yxmd",
        workflow_name=name,
        complexity=ComplexityScore(
            total_score=complexity,
            level="Low",
            node_count=nodes,
            edge_count=nodes - 1,
            unique_tool_types=3,
            unsupported_count=0,
            expression_count=0,
            max_dag_depth=2,
            has_macro_refs=False,
        ),
        coverage=CoverageReport(
            total_nodes=nodes,
            unique_tool_types={"Input", "Filter", "Output"},
            supported_types={"Input", "Filter", "Output"},
            unsupported_types=set(),
            coverage_percentage=coverage,
        ),
        node_count=nodes,
        connection_count=nodes - 1,
        tool_types_used={"Input", "Filter", "Output"},
        estimated_effort=effort,
    )


class TestScoring:
    def test_score_is_value_times_readiness_over_effort(self):
        planner = MigrationWavePlanner()
        plan = planner.plan([_analysis("w", nodes=50, coverage=100.0, complexity=20.0)], [])
        entry = plan.waves[0].workflows[0]
        # value = min(100, 50/50*100) = 100; readiness = 100; effort = 20
        assert entry.value == 100.0
        assert entry.readiness == 100.0
        assert entry.effort == 20.0
        assert entry.score == 500.0

    def test_zero_complexity_floored_to_one(self):
        planner = MigrationWavePlanner()
        plan = planner.plan([_analysis("w", nodes=10, coverage=100.0, complexity=0.0)], [])
        assert plan.waves[0].workflows[0].effort == 1.0

    def test_higher_score_sorts_first_within_wave(self):
        planner = MigrationWavePlanner()
        analyses = [
            _analysis("low", nodes=5, coverage=50.0, complexity=40.0),
            _analysis("high", nodes=50, coverage=100.0, complexity=10.0),
        ]
        plan = planner.plan(analyses, [])
        # No dependencies → all in wave 1, sorted by descending score.
        names = [e.workflow_name for e in plan.waves[0].workflows]
        assert names == ["high", "low"]


class TestWaveLayering:
    def test_chain_produces_sequential_waves(self):
        planner = MigrationWavePlanner()
        analyses = [_analysis("a"), _analysis("b"), _analysis("c")]
        deps = [
            ArtifactDependency("a", "b", "x"),
            ArtifactDependency("b", "c", "y"),
        ]
        plan = planner.plan(analyses, deps)
        wave_of = {e.workflow_name: w.wave for w in plan.waves for e in w.workflows}
        assert wave_of["a"] == 1
        assert wave_of["b"] == 2
        assert wave_of["c"] == 3

    def test_depends_on_recorded(self):
        planner = MigrationWavePlanner()
        plan = planner.plan(
            [_analysis("a"), _analysis("b")],
            [ArtifactDependency("a", "b", "x")],
        )
        b = next(e for w in plan.waves for e in w.workflows if e.workflow_name == "b")
        assert b.depends_on == ["a"]

    def test_diamond_dependency(self):
        planner = MigrationWavePlanner()
        analyses = [_analysis(n) for n in ("a", "b", "c", "d")]
        deps = [
            ArtifactDependency("a", "b", "x"),
            ArtifactDependency("a", "c", "y"),
            ArtifactDependency("b", "d", "z"),
            ArtifactDependency("c", "d", "w"),
        ]
        plan = planner.plan(analyses, deps)
        wave_of = {e.workflow_name: w.wave for w in plan.waves for e in w.workflows}
        assert wave_of["a"] == 1
        assert wave_of["b"] == 2
        assert wave_of["c"] == 2
        assert wave_of["d"] == 3

    def test_cycle_is_broken_and_terminates(self):
        planner = MigrationWavePlanner()
        analyses = [_analysis("a"), _analysis("b")]
        deps = [
            ArtifactDependency("a", "b", "x"),
            ArtifactDependency("b", "a", "y"),
        ]
        plan = planner.plan(analyses, deps)
        # Both still placed; planning did not hang or crash.
        assert plan.workflow_count == 2


class TestEffortEstimate:
    def test_effort_days_mapping(self):
        assert _effort_days("Low") == 1.0
        assert _effort_days("Medium") == 3.0
        assert _effort_days("High") == 8.0
        assert _effort_days("weird") == 3.0

    def test_public_wrapper(self):
        assert days_for_effort("High") == 8.0

    def test_total_effort_days(self):
        planner = MigrationWavePlanner()
        plan = planner.plan(
            [_analysis("a", effort="High"), _analysis("b", effort="Low")],
            [],
        )
        assert plan.total_effort_days == 9.0
