"""Cluster-size / DBU recommendation + rolled-up optimization advisory."""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from a2d.config import CLOUD_NODE_TYPE_IDS, ConversionConfig
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    BufferNode,
    CreatePointsNode,
    DistanceNode,
    FindNearestNode,
    GeocoderNode,
    JoinNode,
    MakeGridNode,
    PredictiveModelNode,
    SpatialMatchNode,
    SummarizeNode,
    TradeAreaNode,
    UnionNode,
)
from a2d.observability.performance_hints import PerformanceAnalyzer, PerformanceHint

_SPATIAL_TYPES = (
    BufferNode,
    SpatialMatchNode,
    CreatePointsNode,
    DistanceNode,
    FindNearestNode,
    GeocoderNode,
    TradeAreaNode,
    MakeGridNode,
)
_SHUFFLE_TYPES = (JoinNode, SummarizeNode, UnionNode)

# Cluster tiers, cheapest first. rel_dbu is a *relative* DBU/hour proxy (not a
# quoted price) so users can compare tiers; workers is the recommended count.
_TIERS: list[dict] = [
    {"tier": "single-node", "workers": 0, "rel_dbu": 1.0, "blurb": "single-node cluster (no workers)"},
    {"tier": "small", "workers": 2, "rel_dbu": 3.0, "blurb": "2 workers"},
    {"tier": "medium", "workers": 4, "rel_dbu": 5.0, "blurb": "4 workers"},
    {"tier": "large", "workers": 8, "rel_dbu": 9.0, "blurb": "8 workers"},
]


@dataclass
class ClusterRecommendation:
    """A starting-cluster recommendation derived from workflow shape."""

    tier: str  # single-node | small | medium | large
    workers: int
    node_type_id: str
    relative_dbu_per_hour: float
    photon_recommended: bool
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tier": self.tier,
            "workers": self.workers,
            "node_type_id": self.node_type_id,
            "relative_dbu_per_hour": self.relative_dbu_per_hour,
            "photon_recommended": self.photon_recommended,
            "rationale": list(self.rationale),
        }


@dataclass
class AdvisorReport:
    """Full advisory: a cluster recommendation + optimization hints."""

    workflow_name: str
    cluster: ClusterRecommendation
    hints: list[PerformanceHint] = field(default_factory=list)
    node_count: int = 0
    max_depth: int = 0

    @property
    def high_priority_hints(self) -> int:
        return sum(1 for h in self.hints if h.priority.value == "high")

    def to_dict(self) -> dict:
        return {
            "workflow_name": self.workflow_name,
            "node_count": self.node_count,
            "max_depth": self.max_depth,
            "cluster": self.cluster.to_dict(),
            "hints": [h.to_dict() for h in self.hints],
            "summary": {
                "hint_count": len(self.hints),
                "high_priority_hints": self.high_priority_hints,
            },
        }


class CostPerformanceAdvisor:
    """Recommend a cluster size and surface Spark optimization hints."""

    def __init__(self) -> None:
        self._perf = PerformanceAnalyzer()

    def analyze(
        self,
        dag: WorkflowDAG,
        config: ConversionConfig | None = None,
        *,
        workflow_name: str = "workflow",
    ) -> AdvisorReport:
        cfg = config or ConversionConfig()
        cluster = self._recommend_cluster(dag, cfg)
        hints = self._perf.analyze(dag)
        return AdvisorReport(
            workflow_name=workflow_name,
            cluster=cluster,
            hints=hints,
            node_count=dag.node_count,
            max_depth=_dag_depth(dag),
        )

    # -- Cluster sizing --

    def _recommend_cluster(self, dag: WorkflowDAG, config: ConversionConfig) -> ClusterRecommendation:
        """Pick a starting tier from a coarse workload score.

        Deliberately simple and transparent (a planning aid, not a benchmark):
        each characteristic adds weight; the total maps to a tier.
        """
        nodes = list(dag.all_nodes())
        node_count = len(nodes)
        depth = _dag_depth(dag)
        shuffle_ops = sum(1 for n in nodes if isinstance(n, _SHUFFLE_TYPES))
        spatial_ops = sum(1 for n in nodes if isinstance(n, _SPATIAL_TYPES))
        ml_ops = sum(1 for n in nodes if isinstance(n, PredictiveModelNode))

        rationale: list[str] = []
        score = 0.0

        score += node_count / 10.0
        if node_count > 20:
            rationale.append(f"{node_count} nodes → larger DAG")
        score += depth / 5.0
        if depth > 8:
            rationale.append(f"DAG depth {depth} → long dependency chain")
        score += shuffle_ops * 1.5
        if shuffle_ops:
            rationale.append(f"{shuffle_ops} shuffle op(s) (join/aggregate/union) → benefit from workers")
        score += spatial_ops * 2.0
        if spatial_ops:
            rationale.append(f"{spatial_ops} spatial op(s) → compute-heavy, size up")
        score += ml_ops * 3.0
        if ml_ops:
            rationale.append(f"{ml_ops} ML/predictive op(s) → size up (MLlib is distributed)")

        # Map score → tier index.
        if score < 2:
            idx = 0
        elif score < 6:
            idx = 1
        elif score < 12:
            idx = 2
        else:
            idx = 3
        # Clamp so extending the score thresholds without adding a tier degrades
        # to the largest tier rather than raising IndexError.
        tier = _TIERS[min(idx, len(_TIERS) - 1)]

        if idx == 0:
            rationale.append("Small, mostly linear workflow → single-node is cheapest and sufficient")

        # Photon accelerates SQL/DataFrame shuffles; recommend it when there are any.
        photon = shuffle_ops > 0
        if photon:
            rationale.append("Photon recommended: SQL/DataFrame joins & aggregations accelerate well")

        return ClusterRecommendation(
            tier=tier["tier"],
            workers=tier["workers"],
            node_type_id=CLOUD_NODE_TYPE_IDS[config.cloud],
            relative_dbu_per_hour=tier["rel_dbu"],
            photon_recommended=photon,
            rationale=rationale,
        )


def _dag_depth(dag: WorkflowDAG) -> int:
    if dag.node_count == 0:
        return 0
    try:
        return nx.dag_longest_path_length(dag._graph) + 1
    except (nx.NetworkXError, nx.NetworkXUnfeasible):
        return dag.node_count
