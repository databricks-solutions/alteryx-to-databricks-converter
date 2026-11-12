"""AI completion — an optional, clearly-marked copy of a converted notebook.

The deterministic converter leaves some cells it could not fully convert: an
unsupported tool emitted as a pass-through, an expression it could not parse, a
connector with a TODO. This module asks a model to fill in **only those cells**
and returns a *separate* notebook with the results spliced in:

* Cells the converter handled are copied byte-for-byte. The model never sees
  or rewrites them.
* Every cell the model wrote is wrapped in ``>>> AI-GENERATED`` /
  ``<<< AI-GENERATED`` markers, and a banner at the top says the file is
  AI-generated and unverified.
* A reply that does not parse as Python, or that drops a variable later cells
  depend on, is rejected: that cell keeps its deterministic version and is
  reported as not completed.

The deterministic notebook is never modified. Callers save this output under a
different name (``<workflow>.ai-completed.py``) so the two can't be confused.

Scope: PySpark notebooks (the converter's primary output), whose cells are
separated by ``# COMMAND ----------`` and start with a ``# Step <node id>:``
header — the structure this module relies on.
"""

from __future__ import annotations

import ast
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

from a2d.advisor.context import Gap, MigrationContext
from a2d.advisor.llm_client import AdvisoryClient, ChatMessage, LLMRequestError
from a2d.ir.graph import WorkflowDAG

logger = logging.getLogger("a2d.advisor.completion")

CELL_SEPARATOR = "\n\n# COMMAND ----------\n\n"
AI_BEGIN = "# >>> AI-GENERATED (unverified) - review before use"
AI_END = "# <<< AI-GENERATED"

# Bounds the model calls one request can make (and so its cost and latency).
MAX_CELLS = 25
MAX_WORKERS = 4
MAX_CONFIG_CHARS = 2000

_STEP_RE = re.compile(r"^# Step (?P<id>\d+):", re.MULTILINE)
_NEEDS_WORK_RE = re.compile(r"\b(TODO|PLACEHOLDER)\b")
_ASSIGN_RE = re.compile(r"^(?P<name>[A-Za-z_]\w*)\s*=(?!=)", re.MULTILINE)
_DF_REF_RE = re.compile(r"\bdf_\w+\b")
_FENCE_RE = re.compile(r"^```[\w-]*\s*\n(?P<body>.*?)\n```\s*$", re.DOTALL)

SYSTEM_PROMPT = """You complete ONE cell of a Databricks PySpark notebook.

A deterministic converter generated the notebook from an Alteryx workflow. It \
could not fully convert this cell. Write a working PySpark replacement for this \
cell only.

Rules:
- Reply with Python code only: no Markdown fences, no explanation outside comments.
- Keep the "# Step <id>:" header line as the first line.
- Assign the same output variable(s) the cell assigns now; later cells use them.
- Read only from the input variables listed, plus `spark`, `F` \
(pyspark.sql.functions) and `Window`, which are already imported.
- Prefer built-in Spark functions over UDFs.
- If something can't be known from what you're given (a table name, a credential, \
a file path), use an obvious placeholder and a "# FILL IN:" comment that says \
what to put there. Never invent table or column names that weren't given.
- Keep it short. Add a one-line comment for any assumption you made.
"""


@dataclass
class CellCompletion:
    """What happened to one cell that needed work."""

    node_id: int | None
    tool_type: str | None
    status: str  # "completed" | "failed" | "skipped"
    reason: str
    before: str
    after: str  # the code spliced in (equals ``before`` unless completed)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "tool_type": self.tool_type,
            "status": self.status,
            "reason": self.reason,
            "before": self.before,
            "after": self.after,
        }


@dataclass
class CompletionResult:
    """The AI-completed copy of a notebook and a per-cell account of it."""

    workflow_name: str
    filename: str
    content: str
    cells: list[CellCompletion] = field(default_factory=list)

    @property
    def completed(self) -> int:
        return sum(1 for c in self.cells if c.status == "completed")

    def to_dict(self) -> dict:
        return {
            "workflow_name": self.workflow_name,
            "filename": self.filename,
            "content": self.content,
            "cells": [c.to_dict() for c in self.cells],
            "summary": {
                "cells_needing_work": len(self.cells),
                "completed": self.completed,
                "failed": sum(1 for c in self.cells if c.status == "failed"),
                "skipped": sum(1 for c in self.cells if c.status == "skipped"),
            },
        }


def completed_filename(workflow_name: str) -> str:
    """The name the AI-completed copy is saved under — never the deterministic one."""
    return f"{workflow_name}.ai-completed.py"


def split_cells(notebook: str) -> list[str]:
    """Split a Databricks source notebook into cells. ``CELL_SEPARATOR.join``
    of the result reproduces the input exactly."""
    return notebook.split(CELL_SEPARATOR)


def _cell_node_id(cell: str) -> int | None:
    m = _STEP_RE.search(cell)
    return int(m.group("id")) if m else None


def _code_lines(cell: str) -> list[str]:
    return [line for line in cell.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _assigned_vars(cell: str) -> list[str]:
    names = [m.group("name") for m in _ASSIGN_RE.finditer("\n".join(_code_lines(cell)))]
    return list(dict.fromkeys(names))


def _input_vars(cell: str) -> list[str]:
    assigned = set(_assigned_vars(cell))
    refs = _DF_REF_RE.findall("\n".join(_code_lines(cell)))
    return [r for r in dict.fromkeys(refs) if r not in assigned]


def _gap_node_ids(ctx: MigrationContext) -> dict[int, list[Gap]]:
    by_node: dict[int, list[Gap]] = {}
    for gap in ctx.gaps:
        if gap.node_id is not None:
            by_node.setdefault(gap.node_id, []).append(gap)
    return by_node


def cells_needing_work(notebook: str, ctx: MigrationContext) -> list[tuple[int, int, str]]:
    """Return ``(cell_index, node_id, cell)`` for every node cell that has a gap
    or carries a TODO/PLACEHOLDER marker. Header, import and footer cells (no
    ``# Step`` header) are never candidates."""
    gap_nodes = _gap_node_ids(ctx)
    found: list[tuple[int, int, str]] = []
    for index, cell in enumerate(split_cells(notebook)):
        node_id = _cell_node_id(cell)
        if node_id is None:
            continue
        if node_id in gap_nodes or _NEEDS_WORK_RE.search(cell):
            found.append((index, node_id, cell))
    return found


def _truncate(text: str, limit: int = MAX_CONFIG_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (truncated, {len(text) - limit} more chars)"


def _source_var(node_id: int, dag: WorkflowDAG, cells_by_node: dict[int, str], depth: int = 0) -> str | None:
    """The DataFrame variable a node receives, read off its predecessor's cell.

    A pass-through (an unsupported tool) emits no assignment — the generator
    hands its input straight to the next step — so its input is whatever its
    single predecessor assigned, following further pass-throughs back. None when
    that can't be told (several inputs, an inlined read, no cell).
    """
    preds = dag.get_predecessors(node_id)
    if len(preds) != 1 or depth > 50:
        return None
    pred = preds[0]
    cell = cells_by_node.get(pred.node_id)
    if cell is not None:
        assigned = [v for v in _assigned_vars(cell) if v.startswith("df_")]
        if assigned:
            preferred = f"df_{pred.node_id}"
            return preferred if preferred in assigned else assigned[-1]
    return _source_var(pred.node_id, dag, cells_by_node, depth + 1)


def _var_owner(var: str, cells_by_node: dict[int, str]) -> int | None:
    for node_id, cell in cells_by_node.items():
        if var in _assigned_vars(cell):
            return node_id
    return None


def _cell_prompt(cell: str, node_id: int, gaps: list[Gap], ctx: MigrationContext, rebind: str | None = None) -> str:
    outputs = _assigned_vars(cell)
    inputs = _input_vars(cell)
    parts = [f"Workflow: {ctx.workflow_name}", f"Alteryx node id: {node_id}"]
    if rebind:
        parts += [
            f"This step is currently a pass-through: it leaves {rebind} unchanged and the next steps read {rebind}.",
            f"Input variable available: {rebind}",
            f"Output: assign your result back to {rebind}.",
        ]
    else:
        parts += [
            f"Input variables available: {', '.join(inputs) if inputs else '(none - this cell reads its own source)'}",
            f"Output variables this cell must assign: {', '.join(outputs) if outputs else '(none)'}",
        ]
    for gap in gaps:
        parts.append(f"Why it needs work: {gap.summary}")
        if gap.tool_type:
            parts.append(f"Alteryx tool: {gap.tool_type}")
        if gap.detail:
            parts.append(f"Converter detail: {gap.detail}")
        if gap.original_configuration:
            cfg = _truncate(json.dumps(gap.original_configuration, indent=2, default=str))
            parts.append(f"Original Alteryx configuration:\n{cfg}")
    parts.append(f"\nThe cell as generated:\n{cell}")
    parts.append("\nReply with the replacement cell.")
    return "\n".join(parts)


def _clean_reply(reply: str) -> str:
    text = reply.strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group("body").strip()
    return text


def _check_reply(code: str, cell: str, rebind: str | None = None) -> str | None:
    """Return why ``code`` can't replace ``cell``, or None if it can."""
    if not code:
        return "the model returned nothing"
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return f"the model's code is not valid Python (line {exc.lineno}: {exc.msg})"
    required = [rebind] if rebind else _assigned_vars(cell)
    missing = [v for v in required if v not in set(_assigned_vars(code))]
    if missing:
        return f"the model's code no longer assigns {', '.join(missing)}, which later cells use"
    return None


def _wrap(code: str) -> str:
    return f"{AI_BEGIN}\n{code}\n{AI_END}"


def _banner(workflow_name: str, completed: int, total: int) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if total == 0:
        body = [
            f"# This is a copy of {workflow_name}.py. The converter finished every cell, so nothing",
            "# was sent to a model and this copy matches the deterministic notebook.",
        ]
    else:
        body = [
            f"# This is a copy of {workflow_name}.py. The converter could not fully convert {total} cell(s);",
            f"# a language model proposed code for {completed} of them. Each one is wrapped in",
            "# AI-GENERATED marker comments. None of it has been run or verified.",
            "# Review every marked cell before you use it.",
        ]
    return "\n".join(
        [
            "# AI-COMPLETED COPY - NOT DETERMINISTIC",
            *body,
            f"# The deterministic notebook ({workflow_name}.py) was not changed. Generated {stamp}.",
        ]
    )


def complete_notebook(
    notebook: str, ctx: MigrationContext, client: AdvisoryClient, dag: WorkflowDAG
) -> CompletionResult:
    """Return an AI-completed copy of ``notebook`` (a PySpark source notebook).

    Only cells that need work are sent to the model, one prompt per cell, a few
    in parallel. ``notebook`` itself is not modified. ``dag`` is the workflow
    graph the notebook was generated from; it tells a pass-through cell which
    DataFrame it receives.
    """
    cells = split_cells(notebook)
    targets = cells_needing_work(notebook, ctx)
    gap_nodes = _gap_node_ids(ctx)
    cells_by_node = {nid: c for c in cells if (nid := _cell_node_id(c)) is not None}

    def run(target: tuple[int, int, str]) -> tuple[int, CellCompletion]:
        index, node_id, cell = target
        gaps = gap_nodes.get(node_id, [])
        tool = next((g.tool_type for g in gaps if g.tool_type), None)

        def outcome(status: str, reason: str, after: str = cell) -> tuple[int, CellCompletion]:
            return index, CellCompletion(node_id, tool, status, reason, cell, after)

        # A pass-through cell assigns nothing; its result has to be bound back to
        # the variable the next steps read. Only safe when nothing else reads it.
        rebind: str | None = None
        if not _assigned_vars(cell) and dag.get_successors(node_id):
            rebind = _source_var(node_id, dag, cells_by_node)
            if rebind is None:
                return outcome(
                    "skipped", "can't tell which DataFrame this step receives, so a result couldn't be wired in"
                )
            owner = _var_owner(rebind, cells_by_node)
            if owner is not None and len(dag.get_successors(owner)) > 1:
                return outcome(
                    "skipped",
                    f"{rebind} also feeds other steps, so replacing it here would change them too",
                )

        messages = [
            ChatMessage(role="system", content=SYSTEM_PROMPT),
            ChatMessage(role="user", content=_cell_prompt(cell, node_id, gaps, ctx, rebind)),
        ]
        try:
            code = _clean_reply(client.chat(messages))
        except LLMRequestError as exc:
            logger.warning("Completion failed for node %s: %s", node_id, exc)
            return outcome("failed", f"the model endpoint returned an error: {exc}")
        problem = _check_reply(code, cell, rebind)
        if problem:
            return outcome("failed", problem)
        return outcome("completed", "", code)

    to_run, over_limit = targets[:MAX_CELLS], targets[MAX_CELLS:]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        outcomes = list(pool.map(run, to_run))
    for index, node_id, cell in over_limit:
        tool = next((g.tool_type for g in gap_nodes.get(node_id, []) if g.tool_type), None)
        outcomes.append(
            (
                index,
                CellCompletion(node_id, tool, "skipped", f"over the {MAX_CELLS}-cell limit for one run", cell, cell),
            )
        )

    out_cells = list(cells)
    for index, completion in outcomes:
        if completion.status == "completed":
            out_cells[index] = _wrap(completion.after)

    report = [c for _, c in sorted(outcomes, key=lambda o: o[0])]
    completed = sum(1 for c in report if c.status == "completed")
    # The banner goes right after the "# Databricks notebook source" line so the
    # file still opens as a notebook.
    out_cells.insert(1, _banner(ctx.workflow_name, completed, len(report)))
    content = CELL_SEPARATOR.join(out_cells)

    return CompletionResult(
        workflow_name=ctx.workflow_name,
        filename=completed_filename(ctx.workflow_name),
        content=content,
        cells=report,
    )
