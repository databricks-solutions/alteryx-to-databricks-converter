"""Review service — builds an interactive-review session from an uploaded file."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from a2d.config import ConversionConfig, OutputFormat
from a2d.parser.workflow_parser import WorkflowParser
from a2d.pipeline import ConversionPipeline
from a2d.review.builder import build_review_session
from server.utils.package import materialize_upload

logger = logging.getLogger("a2d.server.services.review")


def build_review(filename: str, content: bytes, output_format: str = "pyspark") -> dict:
    """Parse one .yxmd/.yxmc file and return a review-session dict.

    Raises :class:`ValueError` for an unknown output format or an unparseable
    workflow (the router maps these to HTTP 422).
    """
    try:
        fmt = OutputFormat(output_format)
    except ValueError as exc:
        raise ValueError(f"unknown output_format {output_format!r}") from exc

    with tempfile.TemporaryDirectory() as tmpdir:
        # .yxzp is unzipped to its primary workflow (macros co-located); others pass through.
        path, was_package = materialize_upload(content, filename, Path(tmpdir))

        config = ConversionConfig(output_format=fmt, expand_macros=was_package)
        parsed = WorkflowParser().parse(path)
        dag = ConversionPipeline(config)._build_dag(parsed)
        session = build_review_session(dag, path.stem, output_format=fmt, config=config)

    logger.info(
        "Built review session for %s [%s]: %d nodes, %d need review",
        filename,
        fmt.value,
        session.total,
        session.needs_review_count,
    )
    return session.to_dict()
