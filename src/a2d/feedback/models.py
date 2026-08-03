"""Data models for feedback capture and learned mappings."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from a2d.llm.models import ConversionCandidate, ProposedNode


def config_signature(tool_type: str, configuration: dict) -> str:
    """Stable signature for a tool + configuration *shape*.

    Keyed on the tool type plus the sorted set of configuration keys (not their
    values), so a learned mapping generalises across workflows that use the same
    tool the same way but with different literal parameters. Deterministic and
    order-insensitive.
    """
    keys = sorted(_flatten_keys(configuration))
    payload = json.dumps({"tool": tool_type, "keys": keys}, sort_keys=True)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"{tool_type}:{digest}"


def _flatten_keys(obj: object, prefix: str = "") -> list[str]:
    """Recursively collect dotted config keys (ignoring list ordering)."""
    keys: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            dotted = f"{prefix}.{k}" if prefix else str(k)
            keys.append(dotted)
            keys.extend(_flatten_keys(v, dotted))
    elif isinstance(obj, list):
        for item in obj:
            keys.extend(_flatten_keys(item, prefix))
    return keys


@dataclass
class LearnedMapping:
    """A conversion learned from a human-accepted / corrected result.

    ``candidate_nodes`` + ``output_ref`` capture the accepted IR sub-graph in the
    same declarative shape a proposer emits, so replaying a mapping is identical
    to consuming a fresh proposal. ``uses`` counts how often it has been applied
    (for ranking and reporting).
    """

    signature: str
    tool_type: str
    candidate_nodes: list[ProposedNode]
    output_ref: str
    rationale: str = ""
    uses: int = 0
    source: str = "user"  # "user" (hand-corrected) or "verified" (accepted proposal)

    def to_candidate(self) -> ConversionCandidate:
        """Materialise this mapping as a ConversionCandidate for the gate."""
        return ConversionCandidate(
            nodes=list(self.candidate_nodes),
            output_ref=self.output_ref,
            rationale=self.rationale or f"Learned mapping for {self.tool_type} (used {self.uses}x)",
            confidence=1.0,
            source="learned",
        )

    def to_dict(self) -> dict:
        return {
            "signature": self.signature,
            "tool_type": self.tool_type,
            "output_ref": self.output_ref,
            "rationale": self.rationale,
            "uses": self.uses,
            "source": self.source,
            "candidate_nodes": [
                {"ref": n.ref, "kind": n.kind, "params": n.params, "inputs": n.inputs} for n in self.candidate_nodes
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> LearnedMapping:
        nodes = [
            ProposedNode(
                ref=n["ref"],
                kind=n["kind"],
                params=n.get("params", {}),
                inputs=n.get("inputs", []),
            )
            for n in data.get("candidate_nodes", [])
        ]
        return cls(
            signature=data["signature"],
            tool_type=data["tool_type"],
            candidate_nodes=nodes,
            output_ref=data["output_ref"],
            rationale=data.get("rationale", ""),
            uses=int(data.get("uses", 0)),
            source=data.get("source", "user"),
        )


@dataclass
class FeedbackStats:
    """Summary of a feedback store's contents."""

    total_mappings: int = 0
    total_uses: int = 0
    by_tool: dict[str, int] = field(default_factory=dict)
