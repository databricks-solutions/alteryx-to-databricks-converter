"""AI completion service — the one place the app produces non-deterministic code.

Converts a workflow deterministically to a PySpark notebook (with the same
options the Convert screen uses, so it starts from the notebook the user
already has), then asks the configured model to fill in only the cells the
converter could not finish. Returns a separate, clearly marked copy; the
deterministic notebook is untouched. See :mod:`a2d.advisor.completion`.

Also renders the Markdown suggestions notes for a workflow without a chat
session, so both AI outputs live on one screen.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from a2d.advisor.completion import complete_notebook
from a2d.advisor.context import MigrationContext, build_migration_context
from a2d.advisor.llm_client import AdvisoryClient
from a2d.advisor.report import render_report
from a2d.config import ConversionConfig, OutputFormat
from a2d.pipeline import ConversionPipeline
from server.models.requests import ConversionOptions
from server.utils.package import materialize_upload

logger = logging.getLogger("a2d.server.services.ai_completion")


def _convert_pyspark(filename: str, content: bytes, opts: ConversionOptions | None, tmpdir: Path):
    path, was_package = materialize_upload(content, filename, tmpdir)
    config = ConversionConfig(
        input_path=path,
        output_dir=tmpdir / "out",
        output_format=OutputFormat.PYSPARK,
        catalog_name=opts.catalog_name if opts else "main",
        schema_name=opts.schema_name if opts else "default",
        include_comments=opts.include_comments if opts else True,
        # A package bundles its macros; expand them like Convert does.
        expand_macros=was_package or bool(opts and opts.expand_macros),
    )
    result = ConversionPipeline(config).convert(path)
    notebook = next((f.content for f in result.output.files if f.filename.endswith(".py")), "")
    ctx = build_migration_context(
        result.dag,
        workflow_name=path.stem,
        output_format=OutputFormat.PYSPARK.value,
        format_warnings=list(result.output.warnings),
        generated_code=notebook,
        coverage=result.output.stats.get("coverage_percentage"),
        confidence=result.confidence.overall if result.confidence else None,
    )
    return result, notebook, ctx


def complete_workflow(
    filename: str,
    content: bytes,
    client: AdvisoryClient,
    opts: ConversionOptions | None = None,
) -> dict:
    """Return the AI-completed PySpark notebook for one workflow, as a dict.

    Raises ValueError when the workflow can't be converted to a notebook.
    """
    with tempfile.TemporaryDirectory() as tmp:
        result, notebook, ctx = _convert_pyspark(filename, content, opts, Path(tmp))
        if not notebook:
            raise ValueError("The converter produced no PySpark notebook for this workflow.")
        completion = complete_notebook(notebook, ctx, client, result.dag)
    payload = completion.to_dict()
    payload["deterministic_filename"] = f"{ctx.workflow_name}.py"
    logger.info(
        "AI completion for %s: %d of %d cell(s) completed",
        filename,
        completion.completed,
        len(completion.cells),
    )
    return payload


def gap_summary(filename: str, content: bytes, opts: ConversionOptions | None = None) -> MigrationContext:
    """The deterministic gap facts for one workflow (no model call)."""
    with tempfile.TemporaryDirectory() as tmp:
        _result, _notebook, ctx = _convert_pyspark(filename, content, opts, Path(tmp))
    return ctx


def suggestions_markdown(
    filename: str, content: bytes, client: AdvisoryClient, opts: ConversionOptions | None = None
) -> tuple[str, str]:
    """Render the Markdown suggestions notes. Returns ``(filename, markdown)``."""
    ctx = gap_summary(filename, content, opts)
    return f"{ctx.workflow_name}_suggestions.md", render_report(ctx, client)
