"""Migration context — the grounding facts an advisory LLM is allowed to see.

This module is pure assembly over data the deterministic pipeline already
produces: unsupported nodes, categorized warnings, deploy readiness, per-node
confidence/method and the generated-code TODO markers. Nothing here calls a
model and nothing here mutates generated code — it only *describes* what the
converter did and where it fell short, so a suggestion can be grounded in facts
instead of guesses.

The same context object backs both the Markdown suggestions report and the chat
session, so the two can never disagree about the migration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import IRNode, UnsupportedNode
from a2d.observability.deploy_status import derive_deploy_status
from a2d.observability.warning_categorization import (
    CategorizedWarnings,
    ParsedWarning,
    categorize_for_format,
)

# A generated-code TODO marker, e.g. "# TODO: replace with a geocoding UDF" or
# "-- TODO: ...". Captured so the report can point at the exact stub text.
_TODO_RE = re.compile(r"^\s*(?:#|--)\s*TODO:\s*(?P<text>.+?)\s*$", re.MULTILINE)

# Confidence at or below which a node is worth explaining even if it converted.
LOW_CONFIDENCE = 0.8


@dataclass
class Gap:
    """One thing the deterministic converter could not fully do.

    A gap is always tied to something concrete — an unsupported node, a warning,
    or a TODO left in the generated code — so a suggestion can be specific.
    """

    kind: str  # "unsupported_tool" | "todo" | "review_warning" | "graph"
    summary: str
    node_id: int | None = None
    tool_type: str | None = None
    detail: str = ""
    # Original Alteryx configuration for an unsupported node, if known. This is
    # the richest signal for suggesting a replacement.
    original_configuration: dict = field(default_factory=dict)
    unsupported_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "summary": self.summary,
            "node_id": self.node_id,
            "tool_type": self.tool_type,
            "detail": self.detail,
            "original_configuration": self.original_configuration,
            "unsupported_reason": self.unsupported_reason,
        }


@dataclass
class NodeDecision:
    """Why the converter treated one node the way it did."""

    node_id: int
    tool_type: str
    annotation: str | None
    confidence: float
    conversion_method: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "tool_type": self.tool_type,
            "annotation": self.annotation,
            "confidence": round(self.confidence, 3),
            "conversion_method": self.conversion_method,
            "notes": list(self.notes),
        }


@dataclass
class MigrationContext:
    """Everything an advisory LLM may reason about for one workflow.

    Read-only by construction: it holds descriptions of the conversion, never
    the mutable artifacts themselves.
    """

    workflow_name: str
    output_format: str
    node_count: int
    edge_count: int
    coverage: float | None
    deploy_status: str
    gaps: list[Gap] = field(default_factory=list)
    decisions: list[NodeDecision] = field(default_factory=list)
    warnings: CategorizedWarnings | None = None

    @property
    def has_gaps(self) -> bool:
        return bool(self.gaps)

    @property
    def blocking_gaps(self) -> list[Gap]:
        """Gaps that stop a clean deploy (unsupported tools and graph breaks)."""
        return [g for g in self.gaps if g.kind in ("unsupported_tool", "graph")]

    def to_dict(self) -> dict:
        return {
            "workflow_name": self.workflow_name,
            "output_format": self.output_format,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "coverage": self.coverage,
            "deploy_status": self.deploy_status,
            "gaps": [g.to_dict() for g in self.gaps],
            "decisions": [d.to_dict() for d in self.decisions],
            "summary": {
                "total_gaps": len(self.gaps),
                "blocking_gaps": len(self.blocking_gaps),
            },
        }


def _gap_from_warning(w: ParsedWarning, kind: str) -> Gap:
    return Gap(
        kind=kind,
        summary=w.title,
        node_id=w.node_id,
        tool_type=w.tool,
        detail=w.detail or w.raw,
    )


def _todo_gaps(generated_code: str) -> list[Gap]:
    """Extract TODO markers the generators left in the emitted code."""
    return [
        Gap(kind="todo", summary=m.group("text"), detail="Left as a TODO in the generated code.")
        for m in _TODO_RE.finditer(generated_code or "")
    ]


def _node_decision(node: IRNode) -> NodeDecision:
    return NodeDecision(
        node_id=node.node_id,
        tool_type=node.original_tool_type,
        annotation=node.annotation,
        confidence=node.conversion_confidence,
        conversion_method=node.conversion_method,
        notes=list(node.conversion_notes),
    )


def build_migration_context(
    dag: WorkflowDAG,
    *,
    workflow_name: str,
    output_format: str,
    workflow_warnings: list[str] | None = None,
    format_warnings: list[str] | None = None,
    generated_code: str = "",
    coverage: float | None = None,
    confidence: float | None = None,
    formats_status: dict[str, str] | None = None,
) -> MigrationContext:
    """Assemble the grounding context for one converted workflow.

    Reuses the existing categorization and deploy-status rules so the advisory
    surfaces agree with what the CLI banner and the Convert page already show.
    """
    wf_warnings = list(workflow_warnings or [])
    fmt_warnings = list(format_warnings or [])

    categorized = categorize_for_format(wf_warnings, fmt_warnings)

    status = derive_deploy_status(
        coverage=coverage,
        confidence=confidence,
        formats_status=formats_status or {output_format: "success"},
        workflow_warnings=wf_warnings,
        best_format_warnings=fmt_warnings,
        best_format=output_format,
    )

    gaps: list[Gap] = []

    # Unsupported nodes carry the most actionable signal: the original config.
    unsupported_by_id: dict[int, UnsupportedNode] = {
        n.node_id: n for n in dag.all_nodes() if isinstance(n, UnsupportedNode)
    }
    for node_id, node in sorted(unsupported_by_id.items()):
        gaps.append(
            Gap(
                kind="unsupported_tool",
                summary=f"{node.original_tool_type} has no deterministic converter",
                node_id=node_id,
                tool_type=node.original_tool_type,
                detail=node.unsupported_reason,
                original_configuration=dict(node.original_configuration),
                unsupported_reason=node.unsupported_reason,
            )
        )

    # Warnings that need a human: missing generator, expression fallback, paths.
    for w in categorized.review:
        gaps.append(_gap_from_warning(w, "review_warning"))
    # Unsupported-tool warnings for nodes not already captured above.
    for w in categorized.unsupported:
        if w.node_id is None or w.node_id not in unsupported_by_id:
            gaps.append(_gap_from_warning(w, "unsupported_tool"))
    for w in categorized.graph:
        gaps.append(_gap_from_warning(w, "graph"))

    gaps.extend(_todo_gaps(generated_code))

    # Decisions worth explaining: anything not a plain high-confidence pass.
    decisions = [
        _node_decision(n)
        for n in dag.all_nodes()
        if n.conversion_confidence < LOW_CONFIDENCE or n.conversion_method != "deterministic" or n.conversion_notes
    ]
    decisions.sort(key=lambda d: d.node_id)

    return MigrationContext(
        workflow_name=workflow_name,
        output_format=output_format,
        node_count=dag.node_count,
        edge_count=dag.edge_count,
        coverage=coverage,
        deploy_status=status,
        gaps=gaps,
        decisions=decisions,
        warnings=categorized,
    )
