"""Data models for portfolio-scale analysis and migration-wave planning."""

from __future__ import annotations

from dataclasses import dataclass, field

from a2d.analyzer.readiness import WorkflowAnalysis


@dataclass
class WorkflowArtifacts:
    """I/O artifacts and structure extracted from a single workflow's IR DAG.

    Paths/tables are *normalized* (lower-cased, whitespace-stripped, ``\\``
    to ``/``) so that a file written by one workflow and read by another match
    regardless of cosmetic differences.
    """

    file_path: str
    workflow_name: str
    reads: set[str] = field(default_factory=set)
    writes: set[str] = field(default_factory=set)
    macros: set[str] = field(default_factory=set)
    # Structural fingerprints of connected sub-flows within this workflow,
    # keyed fingerprint -> human-readable description of the segment.
    subflow_fingerprints: dict[str, str] = field(default_factory=dict)


@dataclass
class ArtifactDependency:
    """A directed data dependency between two workflows via a shared artifact.

    ``producer`` writes ``artifact``; ``consumer`` reads it. The consumer must
    migrate in the same or a later wave than the producer.
    """

    producer: str  # workflow_name that writes the artifact
    consumer: str  # workflow_name that reads the artifact
    artifact: str  # normalized path/table shared between them


@dataclass
class SharedMacro:
    """A macro (.yxmc) referenced by more than one workflow."""

    macro_path: str
    used_by: list[str] = field(default_factory=list)

    @property
    def usage_count(self) -> int:
        return len(self.used_by)


@dataclass
class DuplicateSubflow:
    """A structurally identical sub-flow appearing in multiple workflows.

    Detected by hashing the ordered tool-type sequence of a connected
    component; a repeated hash across workflows flags a copy-paste pattern
    that should be migrated once as a shared asset.
    """

    fingerprint: str
    description: str
    node_count: int
    found_in: list[str] = field(default_factory=list)

    @property
    def occurrence_count(self) -> int:
        return len(self.found_in)


@dataclass
class WorkflowEntry:
    """Per-workflow rollup used by the wave planner.

    ``value``, ``readiness`` and ``effort`` are 0-100 scores derived from the
    underlying :class:`WorkflowAnalysis`; ``score`` is the composite ranking
    ``value * readiness / effort`` (higher = migrate sooner).
    """

    workflow_name: str
    file_path: str
    node_count: int
    coverage_pct: float
    complexity_score: float
    migration_priority: str
    estimated_effort: str
    value: float
    readiness: float
    effort: float
    score: float
    # Names of workflows this one depends on (must migrate first/together).
    depends_on: list[str] = field(default_factory=list)


@dataclass
class WaveAssignment:
    """One migration wave: a set of workflows that can be tackled together."""

    wave: int
    workflows: list[WorkflowEntry] = field(default_factory=list)

    @property
    def total_effort_days(self) -> float:
        return sum(_effort_days(w.estimated_effort) for w in self.workflows)


@dataclass
class MigrationPlan:
    """A sequenced, dependency-ordered migration plan across the estate."""

    waves: list[WaveAssignment] = field(default_factory=list)

    @property
    def total_effort_days(self) -> float:
        return sum(w.total_effort_days for w in self.waves)

    @property
    def workflow_count(self) -> int:
        return sum(len(w.workflows) for w in self.waves)


@dataclass
class PortfolioReport:
    """Complete portfolio analysis across many workflows."""

    analyses: list[WorkflowAnalysis]
    artifacts: list[WorkflowArtifacts]
    dependencies: list[ArtifactDependency]
    shared_macros: list[SharedMacro]
    duplicate_subflows: list[DuplicateSubflow]
    plan: MigrationPlan
    # Workflow names with no producers/consumers and no shared assets.
    isolated_workflows: list[str] = field(default_factory=list)

    @property
    def workflow_count(self) -> int:
        return len(self.analyses)


# ---------------------------------------------------------------------------
# Effort-estimate helpers (shared by planner + models)
# ---------------------------------------------------------------------------

# Rough person-day estimate per effort bucket. Deliberately coarse — this is a
# planning aid, not a quote. Tune centrally here.
_EFFORT_DAYS: dict[str, float] = {"Low": 1.0, "Medium": 3.0, "High": 8.0}


def _effort_days(effort: str) -> float:
    """Map a qualitative effort bucket to a person-day estimate."""
    return _EFFORT_DAYS.get(effort, 3.0)
