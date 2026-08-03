"""Data models for the interactive review workspace."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from a2d.ir.nodes import IRNode, UnsupportedNode

# Per-node conversion status (how the auto-conversion turned out).
ReviewStatus = Literal["auto_accepted", "needs_review", "cannot_convert"]

# Reviewer decision state (what the human did with it). Starts "pending".
ReviewDecision = Literal["pending", "accepted", "edited", "rejected"]

# Confidence at/above this is treated as safe-to-auto-accept (mirrors the
# deploy-status READY_CONFIDENCE bar used elsewhere, expressed 0..1 here).
_AUTO_ACCEPT_CONFIDENCE = 0.8


def node_review_status(node: IRNode, warnings: list[str]) -> ReviewStatus:
    """Classify how a node's auto-conversion turned out.

    * ``cannot_convert`` — an UnsupportedNode (no dataflow-safe conversion).
    * ``needs_review`` — converted but low confidence or carrying warnings.
    * ``auto_accepted`` — high confidence and no warnings.
    """
    if isinstance(node, UnsupportedNode):
        return "cannot_convert"
    if warnings or node.conversion_confidence < _AUTO_ACCEPT_CONFIDENCE:
        return "needs_review"
    return "auto_accepted"


@dataclass
class ReviewNode:
    """One node in the review workspace: canvas metadata + generated code."""

    node_id: int
    tool_type: str
    annotation: str | None
    position: tuple[float, float]
    status: ReviewStatus
    confidence: float
    generated_code: str
    warnings: list[str] = field(default_factory=list)
    conversion_method: str = "deterministic"
    # Reviewer state (mutable).
    decision: ReviewDecision = "pending"
    edited_code: str | None = None

    @property
    def effective_code(self) -> str:
        """The code to emit — the reviewer's edit if any, else the generated code."""
        return self.edited_code if self.edited_code is not None else self.generated_code

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "tool_type": self.tool_type,
            "annotation": self.annotation,
            "position_x": self.position[0],
            "position_y": self.position[1],
            "status": self.status,
            "confidence": round(self.confidence, 3),
            "conversion_method": self.conversion_method,
            "generated_code": self.generated_code,
            "warnings": list(self.warnings),
            "decision": self.decision,
            "edited_code": self.edited_code,
        }


@dataclass
class ReviewEdge:
    """A connection between two review nodes (for the canvas view)."""

    source_id: int
    target_id: int
    origin_anchor: str
    destination_anchor: str

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "origin_anchor": self.origin_anchor,
            "destination_anchor": self.destination_anchor,
        }


@dataclass
class ReviewSession:
    """A reviewable conversion: nodes + edges + aggregate review progress."""

    workflow_name: str
    output_format: str
    nodes: list[ReviewNode] = field(default_factory=list)
    edges: list[ReviewEdge] = field(default_factory=list)

    # -- Lookups --

    def get(self, node_id: int) -> ReviewNode:
        for n in self.nodes:
            if n.node_id == node_id:
                return n
        raise KeyError(f"node {node_id} not in review session")

    # -- Reviewer actions --

    def accept(self, node_id: int) -> ReviewNode:
        node = self.get(node_id)
        node.decision = "accepted"
        return node

    def reject(self, node_id: int) -> ReviewNode:
        node = self.get(node_id)
        node.decision = "rejected"
        return node

    def edit(self, node_id: int, code: str) -> ReviewNode:
        """Override a node's code with a reviewer edit."""
        node = self.get(node_id)
        node.edited_code = code
        node.decision = "edited"
        return node

    # -- Progress --

    @property
    def total(self) -> int:
        return len(self.nodes)

    @property
    def needs_review_count(self) -> int:
        return sum(1 for n in self.nodes if n.status in ("needs_review", "cannot_convert"))

    @property
    def resolved_count(self) -> int:
        """Nodes a reviewer has explicitly acted on."""
        return sum(1 for n in self.nodes if n.decision != "pending")

    @property
    def is_complete(self) -> bool:
        """True when every node that needs review has a reviewer decision."""
        return all(n.decision != "pending" for n in self.nodes if n.status in ("needs_review", "cannot_convert"))

    def to_dict(self) -> dict:
        return {
            "workflow_name": self.workflow_name,
            "output_format": self.output_format,
            "summary": {
                "total": self.total,
                "needs_review": self.needs_review_count,
                "resolved": self.resolved_count,
                "complete": self.is_complete,
            },
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }
