"""Portfolio service — estate-wide analysis over many uploaded workflows.

Wraps :class:`~a2d.portfolio.analyzer.PortfolioAnalyzer` and reuses the CLI's own
serializer (:func:`a2d.portfolio.report.to_dict`) so the web UI and
``a2d portfolio --json`` cannot describe the same estate differently.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from a2d.portfolio.analyzer import PortfolioAnalyzer
from a2d.portfolio.report import to_dict
from server.utils.validation import sanitize_filename

logger = logging.getLogger("a2d.server.services.portfolio")


def analyze_portfolio(files: list[tuple[str, bytes]]) -> dict:
    """Run a portfolio analysis over uploaded workflows.

    Raises :class:`ValueError` when no usable workflow was supplied, so the router
    can answer 422 rather than returning an empty estate that looks like a result.
    """
    if not files:
        raise ValueError("at least one workflow file is required")

    with tempfile.TemporaryDirectory() as tmpdir:
        paths: list[Path] = []
        for filename, content in files:
            path = Path(tmpdir) / sanitize_filename(filename)
            path.write_bytes(content)
            paths.append(path)

        report = PortfolioAnalyzer().analyze(paths)
        payload = to_dict(report)

    logger.info(
        "Portfolio analysis: %d workflow(s), %d dependency(ies), %d wave(s)",
        report.workflow_count,
        len(report.dependencies),
        len(report.plan.waves),
    )
    return payload
