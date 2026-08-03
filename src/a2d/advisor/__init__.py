"""Cost & performance advisor.

Turns an IR DAG into an actionable, cost-oriented advisory:

* a **cluster-size / DBU recommendation** — pick a starting cluster tier
  (single-node → small → medium → large) from workflow characteristics
  (node count, DAG depth, joins/aggregations, spatial/ML presence), estimate a
  relative DBU/hour, and name the cloud ``node_type_id``; and
* **Spark optimization hints** — reuses the existing per-node
  :class:`~a2d.observability.performance_hints.PerformanceAnalyzer`
  (broadcast joins, cross joins, persist/repartition, sequential joins).

Both are pure functions of the IR — deterministic and offline. Exposed as the
``a2d advise`` CLI command.

Alongside the deterministic cost advisor, this package hosts the **opt-in,
advisory-only** LLM surface: :mod:`a2d.advisor.context` assembles the grounding
facts, :mod:`a2d.advisor.llm_client` talks to a configured Foundation Model API
endpoint (and only when one is configured), and :mod:`a2d.advisor.report` renders
a standalone Markdown suggestions document. The model never edits generated code.
"""

from __future__ import annotations

from a2d.advisor.chat import MigrationChat
from a2d.advisor.context import (
    Gap,
    MigrationContext,
    NodeDecision,
    build_migration_context,
)
from a2d.advisor.cost import (
    AdvisorReport,
    ClusterRecommendation,
    CostPerformanceAdvisor,
)
from a2d.advisor.llm_client import (
    AdvisoryClient,
    ChatMessage,
    FMAPIClient,
    LLMNotConfiguredError,
    LLMRequestError,
    resolve_client,
)
from a2d.advisor.report import CLARIFYING_QUESTIONS, render_report

__all__ = [
    "CLARIFYING_QUESTIONS",
    "AdvisorReport",
    "AdvisoryClient",
    "ChatMessage",
    "ClusterRecommendation",
    "CostPerformanceAdvisor",
    "FMAPIClient",
    "Gap",
    "LLMNotConfiguredError",
    "LLMRequestError",
    "MigrationChat",
    "MigrationContext",
    "NodeDecision",
    "build_migration_context",
    "render_report",
    "resolve_client",
]
