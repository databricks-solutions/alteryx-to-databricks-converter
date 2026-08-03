"""Portfolio-scale analysis: migrate the estate, not the file.

This package operates across *many* Alteryx workflows at once:

* :mod:`a2d.portfolio.extract` pulls the I/O artifacts, macro references and
  structural segments out of each workflow's IR DAG.
* :mod:`a2d.portfolio.analyzer` builds the cross-workflow dependency graph and
  detects shared macros and duplicate sub-flows.
* :mod:`a2d.portfolio.planner` ranks workflows by value x readiness / effort and
  sequences them into dependency-ordered migration waves.
* :mod:`a2d.portfolio.report` renders the console / HTML / JSON output.
"""

from __future__ import annotations

from a2d.portfolio.analyzer import PortfolioAnalyzer
from a2d.portfolio.dashboard import EstateRollup, build_rollup, generate_dashboard, risk_tier
from a2d.portfolio.models import (
    ArtifactDependency,
    DuplicateSubflow,
    MigrationPlan,
    PortfolioReport,
    SharedMacro,
    WaveAssignment,
    WorkflowArtifacts,
    WorkflowEntry,
)
from a2d.portfolio.planner import MigrationWavePlanner

__all__ = [
    "ArtifactDependency",
    "DuplicateSubflow",
    "EstateRollup",
    "MigrationPlan",
    "MigrationWavePlanner",
    "PortfolioAnalyzer",
    "PortfolioReport",
    "SharedMacro",
    "WaveAssignment",
    "WorkflowArtifacts",
    "WorkflowEntry",
    "build_rollup",
    "generate_dashboard",
    "risk_tier",
]
