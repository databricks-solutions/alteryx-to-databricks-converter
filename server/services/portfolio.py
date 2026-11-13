"""Portfolio service — estate-wide analysis over many uploaded workflows.

Wraps :class:`~a2d.portfolio.analyzer.PortfolioAnalyzer` and reuses the CLI's own
serializer (:func:`a2d.portfolio.report.to_dict`) so the web UI and
``a2d portfolio --json`` cannot describe the same estate differently.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from a2d.analyzer.batch import BatchAnalyzer
from a2d.portfolio.analyzer import PortfolioAnalyzer
from a2d.portfolio.report import to_dict
from server.utils.package import macro_files, materialize_uploads, write_macro_library

logger = logging.getLogger("a2d.server.services.portfolio")


def analyze_portfolio(files: list[tuple[str, bytes]]) -> dict:
    """Run a portfolio analysis over uploaded workflows.

    Raises :class:`ValueError` when no usable workflow was supplied, so the router
    can answer 422 rather than returning an empty estate that looks like a result.
    """
    if not files:
        raise ValueError("at least one workflow file is required")

    with tempfile.TemporaryDirectory() as tmpdir:
        # .yxzp packages are unzipped to their primary workflow; other files pass through.
        paths = materialize_uploads(files, Path(tmpdir))
        if not paths:
            raise ValueError("at least one workflow file is required (macros alone aren't an estate)")
        # Same macro-expanding analyzer as Assess, so a workflow's coverage and
        # tool counts are the same on every tab.
        batch = BatchAnalyzer(
            expand_macros=True, macro_search_paths=write_macro_library(macro_files(files), Path(tmpdir))
        )
        report = PortfolioAnalyzer(batch).analyze(paths)
        payload = to_dict(report)

    logger.info(
        "Portfolio analysis: %d workflow(s), %d dependency(ies), %d wave(s)",
        report.workflow_count,
        len(report.dependencies),
        len(report.plan.waves),
    )
    return payload
