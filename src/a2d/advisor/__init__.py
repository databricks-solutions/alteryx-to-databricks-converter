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
"""

from __future__ import annotations

from a2d.advisor.cost import (
    AdvisorReport,
    ClusterRecommendation,
    CostPerformanceAdvisor,
)

__all__ = [
    "AdvisorReport",
    "ClusterRecommendation",
    "CostPerformanceAdvisor",
]
