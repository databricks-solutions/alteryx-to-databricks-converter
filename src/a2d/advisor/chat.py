"""Grounded chat about one migration — discussion only, never code edits.

A :class:`MigrationChat` wraps a :class:`~a2d.advisor.context.MigrationContext`
and a configured advisory client. Every model turn is grounded in the facts the
deterministic converter produced, so the assistant can explain *why* a node was
converted the way it was, discuss trade-offs, and answer questions about the
gaps.

Two hard limits, enforced here rather than trusted to the prompt:

* the assistant only ever returns text — this module exposes no path to write a
  file or mutate a DAG; and
* the report is produced by :func:`a2d.advisor.report.render_report`, a separate
  document, so a chat can never rewrite generated code.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from a2d.advisor.context import MigrationContext
from a2d.advisor.llm_client import AdvisoryClient, ChatMessage, LLMRequestError
from a2d.advisor.report import CLARIFYING_QUESTIONS, render_report

logger = logging.getLogger("a2d.advisor.chat")

MAX_HISTORY_TURNS = 20

CHAT_SYSTEM_PROMPT = """You are a migration advisor for a tool that converts Alteryx \
workflows to Databricks code.

The conversion has already happened deterministically. You are here to DISCUSS it: \
explain why the converter made the choices it did, talk through trade-offs, and \
suggest how a human could implement the parts it could not convert.

Hard rules:
- You cannot modify, rewrite, or regenerate any file. Never claim you have. If the \
user asks you to change the generated code, explain that you can only suggest \
changes, which they apply themselves (or capture in the downloadable report).
- Ground every claim in the migration facts provided below. If something is not in \
those facts, say you do not know rather than guessing.
- Be concrete and Databricks-specific. Keep answers brief unless asked to expand.
"""


def _facts_block(ctx: MigrationContext) -> str:
    """Compact, factual grounding payload for the system turn."""
    facts = {
        "workflow": ctx.workflow_name,
        "target_format": ctx.output_format,
        "nodes": ctx.node_count,
        "edges": ctx.edge_count,
        "coverage_percent": ctx.coverage,
        "deploy_status": ctx.deploy_status,
        "gaps": [
            {
                "kind": g.kind,
                "summary": g.summary,
                "node_id": g.node_id,
                "tool_type": g.tool_type,
                "detail": g.detail,
            }
            for g in ctx.gaps
        ],
        "decisions": [d.to_dict() for d in ctx.decisions],
    }
    return json.dumps(facts, indent=2, default=str)


@dataclass
class MigrationChat:
    """A grounded conversation about one converted workflow."""

    context: MigrationContext
    client: AdvisoryClient
    history: list[ChatMessage] = field(default_factory=list)

    def _system_turn(self) -> ChatMessage:
        return ChatMessage(
            role="system",
            content=f"{CHAT_SYSTEM_PROMPT}\n\nMigration facts (authoritative):\n{_facts_block(self.context)}",
        )

    def opening_summary(self) -> str:
        """A deterministic first message — no model call needed to start."""
        gap_count = len(self.context.gaps)
        blocking = len(self.context.blocking_gaps)
        parts = [
            f"I've loaded **{self.context.workflow_name}** "
            f"({self.context.node_count} nodes, {self.context.edge_count} edges), "
            f"converted to `{self.context.output_format}`.",
            f"Deploy readiness is **{self.context.deploy_status}**"
            + (f" with {self.context.coverage:.1f}% coverage." if self.context.coverage is not None else "."),
        ]
        if gap_count:
            parts.append(
                f"There are **{gap_count} gap(s)** the deterministic converter couldn't fully "
                f"handle ({blocking} blocking). Ask me about any of them, about why a node was "
                "converted a particular way, or say *generate report* for downloadable notes."
            )
        else:
            parts.append(
                "Every node converted deterministically — no gaps. Ask me about any conversion "
                "choice if you want the reasoning."
            )
        parts.append("_I can only advise: I never modify the generated files._")
        return " ".join(parts)

    def ask(self, question: str) -> str:
        """Send a user turn and return the assistant's reply text."""
        self.history.append(ChatMessage(role="user", content=question))
        # Keep the transcript bounded; the system turn is always re-sent.
        recent = self.history[-MAX_HISTORY_TURNS:]
        try:
            reply = self.client.chat([self._system_turn(), *recent]).strip()
        except LLMRequestError as exc:
            logger.warning("Chat turn failed: %s", exc)
            # Don't poison the transcript with a failed turn.
            self.history.pop()
            raise
        self.history.append(ChatMessage(role="assistant", content=reply))
        return reply

    def clarifying_questions(self) -> list[str]:
        """Questions to ask before generating the report."""
        return list(CLARIFYING_QUESTIONS)

    def generate_report(self, answers: dict[str, str] | None = None) -> str:
        """Render the standalone Markdown report for this migration.

        Returns document text; writing it to disk (or serving it as a download)
        is the caller's job. Nothing here touches generated code.
        """
        return render_report(self.context, self.client, answers=answers)
