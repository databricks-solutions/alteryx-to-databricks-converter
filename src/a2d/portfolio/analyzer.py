"""Cross-workflow portfolio analysis.

Parses every workflow in a directory once, extracts its I/O artifacts / macros
/ sub-flow fingerprints, then links workflows together into a dependency graph
and detects shared assets across the estate.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

from a2d.analyzer.batch import BatchAnalyzer
from a2d.analyzer.readiness import WorkflowAnalysis
from a2d.exceptions import A2dError
from a2d.parser.workflow_parser import WorkflowParser
from a2d.portfolio.extract import extract_artifacts
from a2d.portfolio.models import (
    ArtifactDependency,
    DuplicateSubflow,
    PortfolioReport,
    SharedMacro,
    WorkflowArtifacts,
)
from a2d.portfolio.planner import MigrationWavePlanner

logger = logging.getLogger("a2d.portfolio.analyzer")


class PortfolioAnalyzer:
    """Analyze many Alteryx workflows as one connected estate."""

    def __init__(self) -> None:
        self._parser = WorkflowParser()
        self._batch = BatchAnalyzer()
        self._planner = MigrationWavePlanner()

    def analyze(self, paths: list[Path]) -> PortfolioReport:
        """Analyze a set of workflow files into a full portfolio report."""
        analyses: list[WorkflowAnalysis] = []
        artifacts: list[WorkflowArtifacts] = []

        for path in paths:
            try:
                parsed = self._parser.parse(path)
                dag = self._batch.build_dag(parsed)
                analysis = self._batch.analyze_workflow(parsed, dag)
                arts = extract_artifacts(
                    workflow_name=analysis.workflow_name,
                    file_path=analysis.file_path,
                    dag=dag,
                    macro_references=parsed.macro_references,
                )
            except A2dError as e:
                logger.error("Failed to analyze %s: %s", path, e)
                continue
            analyses.append(analysis)
            artifacts.append(arts)

        dependencies = self._build_dependencies(artifacts)
        shared_macros = self._detect_shared_macros(artifacts)
        duplicate_subflows = self._detect_duplicate_subflows(artifacts)
        isolated = self._find_isolated(artifacts, dependencies, shared_macros, duplicate_subflows)

        plan = self._planner.plan(analyses, dependencies)

        return PortfolioReport(
            analyses=analyses,
            artifacts=artifacts,
            dependencies=dependencies,
            shared_macros=shared_macros,
            duplicate_subflows=duplicate_subflows,
            plan=plan,
            isolated_workflows=isolated,
        )

    # ── Dependency graph ─────────────────────────────────────────────────

    @staticmethod
    def _build_dependencies(artifacts: list[WorkflowArtifacts]) -> list[ArtifactDependency]:
        """Link producers to consumers via shared normalized artifacts.

        For each artifact written by workflow A and read by workflow B (A != B)
        we emit a producer->consumer dependency. Self-loops (a workflow reading
        what it wrote) are ignored.
        """
        producers: dict[str, list[str]] = defaultdict(list)
        for art in artifacts:
            for written in art.writes:
                producers[written].append(art.workflow_name)

        deps: list[ArtifactDependency] = []
        seen: set[tuple[str, str, str]] = set()
        for art in artifacts:
            for read in art.reads:
                for producer in producers.get(read, []):
                    if producer == art.workflow_name:
                        continue
                    key = (producer, art.workflow_name, read)
                    if key in seen:
                        continue
                    seen.add(key)
                    deps.append(
                        ArtifactDependency(
                            producer=producer,
                            consumer=art.workflow_name,
                            artifact=read,
                        )
                    )
        deps.sort(key=lambda d: (d.producer, d.consumer, d.artifact))
        return deps

    # ── Shared macros ──────────────────────────────────────────────────────

    @staticmethod
    def _detect_shared_macros(artifacts: list[WorkflowArtifacts]) -> list[SharedMacro]:
        """Find macros referenced by more than one workflow."""
        macro_users: dict[str, list[str]] = defaultdict(list)
        for art in artifacts:
            for macro in art.macros:
                macro_users[macro].append(art.workflow_name)

        shared = [
            SharedMacro(macro_path=macro, used_by=sorted(set(users)))
            for macro, users in macro_users.items()
            if len(set(users)) > 1
        ]
        shared.sort(key=lambda m: (-m.usage_count, m.macro_path))
        return shared

    # ── Duplicate sub-flows ──────────────────────────────────────────────

    @staticmethod
    def _detect_duplicate_subflows(artifacts: list[WorkflowArtifacts]) -> list[DuplicateSubflow]:
        """Find structurally identical sub-flows appearing in >1 workflow."""
        by_fingerprint: dict[str, list[str]] = defaultdict(list)
        descriptions: dict[str, str] = {}
        for art in artifacts:
            for fingerprint, description in art.subflow_fingerprints.items():
                by_fingerprint[fingerprint].append(art.workflow_name)
                descriptions[fingerprint] = description

        duplicates: list[DuplicateSubflow] = []
        for fingerprint, workflows in by_fingerprint.items():
            unique_workflows = sorted(set(workflows))
            if len(unique_workflows) < 2:
                continue
            description = descriptions[fingerprint]
            node_count = description.count(",") + 1 if description else 0
            duplicates.append(
                DuplicateSubflow(
                    fingerprint=fingerprint,
                    description=description,
                    node_count=node_count,
                    found_in=unique_workflows,
                )
            )
        duplicates.sort(key=lambda d: (-d.occurrence_count, d.fingerprint))
        return duplicates

    # ── Isolated workflows ───────────────────────────────────────────────

    @staticmethod
    def _find_isolated(
        artifacts: list[WorkflowArtifacts],
        dependencies: list[ArtifactDependency],
        shared_macros: list[SharedMacro],
        duplicate_subflows: list[DuplicateSubflow],
    ) -> list[str]:
        """Workflows with no cross-workflow links of any kind."""
        linked: set[str] = set()
        for dep in dependencies:
            linked.add(dep.producer)
            linked.add(dep.consumer)
        for macro in shared_macros:
            linked.update(macro.used_by)
        for dup in duplicate_subflows:
            linked.update(dup.found_in)

        return sorted(art.workflow_name for art in artifacts if art.workflow_name not in linked)
