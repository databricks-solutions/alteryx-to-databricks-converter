"""Migration-wave planner.

Ranks workflows by ``value x readiness / effort`` and sequences them into
dependency-ordered waves: a consumer never migrates before the workflow that
produces the data it reads.
"""

from __future__ import annotations

import logging

import networkx as nx

from a2d.analyzer.readiness import WorkflowAnalysis
from a2d.portfolio.models import (
    ArtifactDependency,
    MigrationPlan,
    WaveAssignment,
    WorkflowEntry,
    _effort_days,
)

logger = logging.getLogger("a2d.portfolio.planner")


class MigrationWavePlanner:
    """Produce a sequenced, dependency-aware migration plan for the estate."""

    def plan(
        self,
        analyses: list[WorkflowAnalysis],
        dependencies: list[ArtifactDependency],
    ) -> MigrationPlan:
        """Rank workflows and assign them to dependency-ordered waves."""
        entries = {a.workflow_name: self._score(a) for a in analyses}

        # Record each workflow's producers so the report can show why it waits.
        for dep in dependencies:
            if dep.consumer in entries and dep.producer in entries:
                depends = entries[dep.consumer].depends_on
                if dep.producer not in depends:
                    depends.append(dep.producer)

        waves = self._assign_waves(entries, dependencies)
        return MigrationPlan(waves=waves)

    # ── Scoring ──────────────────────────────────────────────────────────

    @staticmethod
    def _score(analysis: WorkflowAnalysis) -> WorkflowEntry:
        """Compute value / readiness / effort and the composite rank score.

        * **value** — a bigger workflow delivers more when migrated, so we use
          node count (scaled, capped at 50 nodes = 100) as a proxy for value.
        * **readiness** — tool coverage percentage; higher = safer to automate.
        * **effort** — complexity score, floored at 1 to avoid divide-by-zero.

        ``score = value * readiness / effort`` — high-value, high-readiness,
        low-effort workflows rank first (the easy, valuable wins).
        """
        value = min(100.0, analysis.node_count / 50.0 * 100.0)
        readiness = analysis.coverage.coverage_percentage
        effort = max(1.0, analysis.complexity.total_score)
        score = value * readiness / effort

        return WorkflowEntry(
            workflow_name=analysis.workflow_name,
            file_path=analysis.file_path,
            node_count=analysis.node_count,
            coverage_pct=analysis.coverage.coverage_percentage,
            complexity_score=analysis.complexity.total_score,
            migration_priority=analysis.migration_priority,
            estimated_effort=analysis.estimated_effort,
            value=round(value, 1),
            readiness=round(readiness, 1),
            effort=round(effort, 1),
            score=round(score, 1),
        )

    # ── Wave assignment ────────────────────────────────────────────────────

    @staticmethod
    def _assign_waves(
        entries: dict[str, WorkflowEntry],
        dependencies: list[ArtifactDependency],
    ) -> list[WaveAssignment]:
        """Layer workflows into waves honoring producer->consumer order.

        A workflow's wave is one greater than the maximum wave of its
        producers (longest-path layering). Cyclic dependencies (rare, but
        possible when two workflows read each other's outputs) are broken by
        dropping back-edges so planning still terminates; within a wave,
        workflows are ordered by descending rank score.
        """
        graph: nx.DiGraph = nx.DiGraph()
        for name in entries:
            graph.add_node(name)
        for dep in dependencies:
            if dep.producer in entries and dep.consumer in entries and dep.producer != dep.consumer:
                graph.add_edge(dep.producer, dep.consumer)

        if not nx.is_directed_acyclic_graph(graph):
            _break_cycles(graph)

        # Longest-path layering: wave = max(producer waves) + 1.
        wave_of: dict[str, int] = {}
        for name in nx.topological_sort(graph):
            preds = list(graph.predecessors(name))
            wave_of[name] = 0 if not preds else max(wave_of[p] for p in preds) + 1

        buckets: dict[int, list[WorkflowEntry]] = {}
        for name, wave in wave_of.items():
            buckets.setdefault(wave, []).append(entries[name])

        waves: list[WaveAssignment] = []
        for wave in sorted(buckets):
            members = sorted(buckets[wave], key=lambda e: (-e.score, e.workflow_name))
            waves.append(WaveAssignment(wave=wave + 1, workflows=members))
        return waves


def _break_cycles(graph: nx.DiGraph) -> None:
    """Remove one edge per cycle so the graph becomes a DAG.

    Mutates *graph* in place. Logs each dropped edge so the ambiguity is
    visible rather than silent.
    """
    while not nx.is_directed_acyclic_graph(graph):
        try:
            cycle = nx.find_cycle(graph)
        except nx.NetworkXNoCycle:  # pragma: no cover - guarded by while
            break
        u, v = cycle[-1][0], cycle[-1][1]
        graph.remove_edge(u, v)
        logger.warning("Broke dependency cycle by dropping edge %s -> %s", u, v)


def days_for_effort(effort: str) -> float:
    """Public wrapper around the shared effort-to-days mapping."""
    return _effort_days(effort)
