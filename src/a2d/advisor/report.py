"""Markdown suggestions report — advisory output, built strictly on the side.

The report is a *separate document*. It is never merged into, and never used to
rewrite, the generated PySpark/SQL/DLT artifacts: those stay byte-for-byte
deterministic. A reviewer reads the suggestions and applies anything useful by
hand.

Structure: a header that states plainly the document is AI-generated and
advisory, a deterministic summary of the migration (facts from
:class:`~a2d.advisor.context.MigrationContext`), then one section per gap with
the model's suggestion. If no endpoint is configured the report is still
produced — with the deterministic facts and an opt-in note instead of
suggestions — so the command is useful either way.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from a2d.advisor.context import Gap, MigrationContext
from a2d.advisor.llm_client import (
    ENV_ENDPOINT,
    AdvisoryClient,
    ChatMessage,
    LLMRequestError,
)

logger = logging.getLogger("a2d.advisor.report")

MAX_CONFIG_CHARS = 1500

SYSTEM_PROMPT = """You are helping migrate an Alteryx workflow to Databricks.

A deterministic converter has already produced the runnable code. Your job is \
ONLY to suggest how a human might implement the parts it could not convert, and \
to explain trade-offs. You are advisory: your output goes into a separate notes \
document, never into the generated code.

Rules:
- Be concrete and Databricks-specific (PySpark, Databricks SQL, Unity Catalog, \
Lakeflow). Prefer built-in functions over UDFs.
- If the original configuration is ambiguous, say what is ambiguous and what you \
assumed. Never invent column or table names that were not given.
- Keep each suggestion tight: what to do, a short code sketch, and any caveat.
- Do not claim to have changed or verified any file. You cannot run code.
"""


def _truncate(text: str, limit: int = MAX_CONFIG_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… (truncated, {len(text) - limit} more chars)"


def _gap_prompt(gap: Gap, ctx: MigrationContext) -> str:
    parts = [
        f"Workflow: {ctx.workflow_name}",
        f"Target format: {ctx.output_format}",
        f"Gap type: {gap.kind}",
        f"Summary: {gap.summary}",
    ]
    if gap.node_id is not None:
        parts.append(f"Alteryx node id: {gap.node_id}")
    if gap.tool_type:
        parts.append(f"Alteryx tool: {gap.tool_type}")
    if gap.detail:
        parts.append(f"Converter detail: {gap.detail}")
    if gap.unsupported_reason:
        parts.append(f"Why unconverted: {gap.unsupported_reason}")
    if gap.original_configuration:
        cfg = _truncate(json.dumps(gap.original_configuration, indent=2, default=str))
        parts.append(f"Original Alteryx configuration:\n```json\n{cfg}\n```")
    parts.append("\nSuggest how to implement this on Databricks. Be specific and note any assumptions.")
    return "\n".join(parts)


def _suggest_for_gap(client: AdvisoryClient, gap: Gap, ctx: MigrationContext) -> str:
    messages = [
        ChatMessage(role="system", content=SYSTEM_PROMPT),
        ChatMessage(role="user", content=_gap_prompt(gap, ctx)),
    ]
    try:
        return client.chat(messages).strip()
    except LLMRequestError as exc:
        logger.warning("Suggestion failed for gap %s: %s", gap.summary, exc)
        return f"_Suggestion unavailable — the model endpoint returned an error: {exc}_"


def _gap_heading(gap: Gap) -> str:
    where = f" (node {gap.node_id})" if gap.node_id is not None else ""
    return f"{gap.summary}{where}"


_KIND_LABEL = {
    "unsupported_tool": "Unsupported tool",
    "todo": "TODO in generated code",
    "review_warning": "Needs review",
    "graph": "Workflow structure",
}


def render_report(
    ctx: MigrationContext,
    client: AdvisoryClient | None = None,
    *,
    answers: dict[str, str] | None = None,
) -> str:
    """Render the Markdown suggestions report for *ctx*.

    ``client`` is optional: without it the report contains the deterministic
    facts plus an opt-in note. ``answers`` carries any clarifying answers the
    user supplied, which are included as context for the model and recorded in
    the document.
    """
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = [
        f"# Migration suggestions — {ctx.workflow_name}",
        "",
        "> **AI-generated advisory notes.** This document was produced by a language "
        "model to suggest implementations for the parts the deterministic converter "
        "could not handle. It is **not** part of the generated code, has **not** been "
        "executed or verified, and no generated file was modified. Review each "
        "suggestion before applying it.",
        "",
        f"- Generated: {generated_at}",
        f"- Target format: `{ctx.output_format}`",
        f"- Workflow size: {ctx.node_count} nodes, {ctx.edge_count} edges",
        f"- Deterministic coverage: {f'{ctx.coverage:.1f}%' if ctx.coverage is not None else 'n/a'}",
        f"- Deploy readiness: `{ctx.deploy_status}`",
        f"- Gaps found: {len(ctx.gaps)} ({len(ctx.blocking_gaps)} blocking)",
        "",
    ]

    if answers:
        lines += ["## Context you provided", ""]
        lines += [f"- **{q}** — {a}" for q, a in answers.items()]
        lines.append("")

    if not ctx.has_gaps:
        lines += [
            "## No gaps found",
            "",
            "The deterministic converter handled every node in this workflow. There is "
            "nothing for a model to suggest — review the generated code as usual.",
            "",
        ]
        return "\n".join(lines)

    if client is None:
        lines += [
            "## Suggestions unavailable (AI is opt-in)",
            "",
            f"No Foundation Model API endpoint is configured, so no suggestions were "
            f"generated. Set `{ENV_ENDPOINT}` to enable them. The gaps below are "
            "reported deterministically and are accurate without a model.",
            "",
        ]

    # Group gaps so a reader sees blockers first.
    ordered = sorted(ctx.gaps, key=lambda g: (g.kind != "unsupported_tool", g.kind, g.node_id or 0))

    lines += ["## Gaps and suggestions", ""]
    for index, gap in enumerate(ordered, start=1):
        label = _KIND_LABEL.get(gap.kind, gap.kind)
        lines += [f"### {index}. {_gap_heading(gap)}", "", f"- Category: {label}"]
        if gap.tool_type:
            lines.append(f"- Alteryx tool: `{gap.tool_type}`")
        if gap.detail:
            lines.append(f"- Converter said: {gap.detail}")
        lines.append("")
        if gap.original_configuration:
            cfg = _truncate(json.dumps(gap.original_configuration, indent=2, default=str), 800)
            lines += [
                "<details><summary>Original Alteryx configuration</summary>",
                "",
                "```json",
                cfg,
                "```",
                "",
                "</details>",
                "",
            ]
        if client is not None:
            lines += ["**Suggested approach**", "", _suggest_for_gap(client, gap, ctx), ""]

    if ctx.decisions:
        lines += ["## Converter decisions worth knowing", ""]
        lines += [
            "These nodes converted, but with reduced confidence or a non-default method — "
            "useful context when reviewing the output.",
            "",
            "| Node | Tool | Confidence | Method | Notes |",
            "|------|------|-----------|--------|-------|",
        ]
        for d in ctx.decisions:
            notes = "; ".join(d.notes) if d.notes else "—"
            lines.append(
                f"| {d.node_id} | {d.tool_type or '—'} | {d.confidence * 100:.0f}% | "
                f"`{d.conversion_method}` | {notes} |"
            )
        lines.append("")

    return "\n".join(lines)


# Questions the chat asks before generating a report, so suggestions fit the
# target environment instead of guessing.
CLARIFYING_QUESTIONS: list[str] = [
    "Which Unity Catalog catalog and schema should the migrated tables live in?",
    "Where does the source data land in Databricks (volume path, existing table, or external location)?",
    "Are there constraints to respect — no UDFs, streaming vs batch, or a required schedule?",
]
