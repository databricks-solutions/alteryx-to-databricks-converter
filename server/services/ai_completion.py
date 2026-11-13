"""AI completion service: the one place the app produces non-deterministic code.

Converts a workflow deterministically to a PySpark notebook (with the same
options the Convert step uses, so it starts from the notebook the user already
has), then asks the configured model to fill in only the steps the converter
could not finish. Returns a separate, clearly marked copy; the deterministic
notebook is untouched. See :mod:`a2d.advisor.completion`.

Also renders the Markdown suggestions notes for a workflow, so both AI outputs
live on one screen.

AI is opt-in: :func:`get_client` returns None when no Foundation Model API
endpoint is configured, and the router turns that into a clear 422.
"""

from __future__ import annotations

import logging
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from a2d.advisor.completion import completable_steps, complete_notebook
from a2d.advisor.context import MigrationContext, build_migration_context
from a2d.advisor.llm_client import AdvisoryClient, resolve_client
from a2d.advisor.report import render_report
from a2d.config import ConversionConfig, OutputFormat
from a2d.ir.graph import WorkflowDAG
from a2d.pipeline import ConversionPipeline
from server.models.requests import ConversionOptions
from server.settings import settings
from server.utils.package import materialize_upload, write_macro_library

logger = logging.getLogger("a2d.server.services.ai_completion")

# Whole completions running at once, across all users. Each one already caps its
# own model calls; this keeps a handful of large requests from queueing up behind
# each other until they all time out. A caller that finds no free slot gets 429.
MAX_CONCURRENT_COMPLETIONS = 2
_completion_slots = threading.BoundedSemaphore(MAX_CONCURRENT_COMPLETIONS)
# Stop starting new model calls this long before the request deadline, so the
# answer (with whatever finished) gets back before the caller gives up.
_DEADLINE_MARGIN_SECONDS = 15.0


class CompletionBusyError(RuntimeError):
    """Too many AI completions are already running."""


def get_client(endpoint: str | None = None, token: str | None = None) -> AdvisoryClient | None:
    """Resolve the advisory client from the request, then server settings."""
    return resolve_client(
        endpoint or settings.fmapi_endpoint or None,
        token or settings.fmapi_token or None,
    )


def is_enabled() -> bool:
    """True when an FMAPI endpoint is configured."""
    return get_client() is not None


@dataclass
class _Converted:
    notebook: str
    ctx: MigrationContext
    dag: WorkflowDAG
    cell_nodes: list[int | None] | None
    node_io: dict[int, dict[str, dict[str, str]]] | None


def _convert_pyspark(
    filename: str,
    content: bytes,
    opts: ConversionOptions | None,
    tmpdir: Path,
    macros: list[tuple[str, bytes]] | None = None,
) -> _Converted:
    """Convert like Convert does (same options, same macros), PySpark only."""
    path, was_package = materialize_upload(content, filename, tmpdir)
    library = write_macro_library(macros or [], tmpdir)
    config = ConversionConfig(
        input_path=path,
        output_dir=tmpdir / "out",
        output_format=OutputFormat.PYSPARK,
        catalog_name=opts.catalog_name if opts else "main",
        schema_name=opts.schema_name if opts else "default",
        include_comments=opts.include_comments if opts else True,
        # A package bundles its macros; expand them like Convert does.
        expand_macros=was_package or (opts.expand_macros if opts else True),
        macro_search_paths=tuple(library),
    )
    result = ConversionPipeline(config).convert(path)
    notebook_file = next((f for f in result.output.files if f.filename.endswith(".py")), None)
    if notebook_file is None:
        raise ValueError("The converter produced no PySpark notebook for this workflow.")
    ctx = build_migration_context(
        result.dag,
        workflow_name=path.stem,
        output_format=OutputFormat.PYSPARK.value,
        format_warnings=list(result.output.warnings),
        generated_code=notebook_file.content,
        coverage=result.output.stats.get("coverage_percentage"),
        confidence=result.confidence.overall if result.confidence else None,
    )
    return _Converted(
        notebook=notebook_file.content,
        ctx=ctx,
        dag=result.dag,
        cell_nodes=result.output.cell_nodes.get(notebook_file.filename),
        node_io=result.output.node_io.get(notebook_file.filename),
    )


def complete_workflow(
    filename: str,
    content: bytes,
    client: AdvisoryClient,
    opts: ConversionOptions | None = None,
    *,
    budget_seconds: float | None = None,
    macros: list[tuple[str, bytes]] | None = None,
) -> dict:
    """Return the AI-completed PySpark notebook for one workflow, as a dict.

    Raises ValueError when the workflow can't be converted to a notebook, and
    :class:`CompletionBusyError` when the concurrency limit is reached.
    """
    if not _completion_slots.acquire(blocking=False):
        raise CompletionBusyError("Other AI completions are running right now. Try again in a minute.")
    try:
        budget = settings.conversion_timeout_seconds if budget_seconds is None else budget_seconds
        deadline = time.monotonic() + max(budget - _DEADLINE_MARGIN_SECONDS, 1.0)
        with tempfile.TemporaryDirectory() as tmp:
            converted = _convert_pyspark(filename, content, opts, Path(tmp), macros)
            completion = complete_notebook(
                converted.notebook,
                converted.ctx,
                client,
                converted.dag,
                converted.cell_nodes,
                deadline=deadline,
                node_io=converted.node_io,
            )
    finally:
        _completion_slots.release()
    payload = completion.to_dict()
    payload["deterministic_filename"] = f"{converted.ctx.workflow_name}.py"
    logger.info(
        "AI completion for %s: %d of %d step(s) completed",
        filename,
        completion.completed,
        len(completion.cells),
    )
    return payload


def _from_step_line(cell: str, node_id: int) -> str:
    """A cell from its ``# Step N:`` line on, the way Review shows a step's code."""
    marker = f"# Step {node_id}:"
    at = cell.find(marker)
    return (cell[at:] if at >= 0 else cell).rstrip()


def suggest_step(
    filename: str,
    content: bytes,
    client: AdvisoryClient,
    node_id: int,
    opts: ConversionOptions | None = None,
    *,
    hint: str | None = None,
    macros: list[tuple[str, bytes]] | None = None,
    budget_seconds: float | None = None,
) -> dict:
    """Ask the model for one step's code, for Review. Same prompt, checks and
    wiring as AI completion; the step needn't be one the converter left
    unfinished, and the reviewer can add a note.

    Returns ``{"node_id", "status", "reason", "code", "before"}`` where ``code``
    (when completed) is the step's cell with the AI code between the markers.
    Raises ValueError when the step has no PySpark code of its own, and
    :class:`CompletionBusyError` when the concurrency limit is reached.
    """
    if not _completion_slots.acquire(blocking=False):
        raise CompletionBusyError("Other AI requests are running right now. Try again in a minute.")
    try:
        budget = settings.conversion_timeout_seconds if budget_seconds is None else budget_seconds
        deadline = time.monotonic() + max(budget - _DEADLINE_MARGIN_SECONDS, 1.0)
        with tempfile.TemporaryDirectory() as tmp:
            converted = _convert_pyspark(filename, content, opts, Path(tmp), macros)
            result = complete_notebook(
                converted.notebook,
                converted.ctx,
                client,
                converted.dag,
                converted.cell_nodes,
                deadline=deadline,
                node_io=converted.node_io,
                only={node_id},
                hint=hint,
            )
    finally:
        _completion_slots.release()
    if not result.cells:
        raise ValueError(f"Step {node_id} has no PySpark code of its own to suggest for.")
    cell = result.cells[0]
    logger.info("AI suggestion for %s step %s: %s", filename, node_id, cell.status)
    return {
        "node_id": node_id,
        "status": cell.status,
        "reason": cell.reason,
        "code": _from_step_line(cell.after, node_id) if cell.status == "completed" else None,
        "before": _from_step_line(cell.before, node_id),
    }


def gap_summary(
    filename: str,
    content: bytes,
    opts: ConversionOptions | None = None,
    macros: list[tuple[str, bytes]] | None = None,
) -> dict:
    """What the converter couldn't finish, and which of those steps AI completion
    would work on. No model call."""
    with tempfile.TemporaryDirectory() as tmp:
        converted = _convert_pyspark(filename, content, opts, Path(tmp), macros)
    payload = converted.ctx.to_dict()
    payload["completable"] = completable_steps(converted.notebook, converted.ctx, converted.dag, converted.cell_nodes)
    return payload


def suggestions_markdown(
    filename: str,
    content: bytes,
    client: AdvisoryClient,
    opts: ConversionOptions | None = None,
    macros: list[tuple[str, bytes]] | None = None,
) -> tuple[str, str]:
    """Render the Markdown suggestions notes. Returns ``(filename, markdown)``."""
    with tempfile.TemporaryDirectory() as tmp:
        converted = _convert_pyspark(filename, content, opts, Path(tmp), macros)
    return f"{converted.ctx.workflow_name}_suggestions.md", render_report(converted.ctx, client)
