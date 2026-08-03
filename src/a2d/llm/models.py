"""Data models for LLM-assisted conversion."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConversionRequest:
    """A request to propose a conversion for one unsupported node.

    Everything the model sees is derived from the parsed node — its resolved
    tool type, raw Alteryx configuration, annotation, and the column names
    arriving on each input anchor (when known from sample data).
    """

    tool_type: str
    plugin_name: str
    configuration: dict
    annotation: str | None = None
    input_columns: dict[str, list[str]] = field(default_factory=dict)
    node_id: int = 0


@dataclass
class ProposedNode:
    """One IR node in a candidate, described declaratively.

    ``kind`` is an IR node class name from the allow-list (e.g. ``"FilterNode"``,
    ``"FormulaNode"``). ``params`` are the constructor kwargs for that class,
    restricted to JSON-serialisable primitives so a model response can be parsed
    without executing anything. ``inputs`` names the upstream ProposedNode
    (by ``ref``) feeding each anchor; an empty list means the candidate's single
    external input feeds this node.
    """

    ref: str
    kind: str
    params: dict = field(default_factory=dict)
    inputs: list[str] = field(default_factory=list)


@dataclass
class ConversionCandidate:
    """A candidate conversion: a small sub-graph of supported IR nodes.

    ``nodes`` are topologically orderable via their ``inputs`` refs. ``output_ref``
    identifies which ProposedNode produces the candidate's result. ``rationale``
    is a short human-readable explanation. ``confidence`` is the proposer's
    self-reported 0..1 score (advisory only — the verification gate is what
    actually decides acceptance).
    """

    nodes: list[ProposedNode]
    output_ref: str
    rationale: str = ""
    confidence: float = 0.0
    source: str = "stub"  # which client produced it ("stub", "databricks", ...)


@dataclass
class VerificationVerdict:
    """Result of running a candidate through the equivalence gate."""

    status: str  # "verified" | "rejected" | "unverified"
    parity_score: float = 0.0
    detail: str = ""

    @property
    def accepted(self) -> bool:
        """True only when the candidate reproduced the expected output."""
        return self.status == "verified"
