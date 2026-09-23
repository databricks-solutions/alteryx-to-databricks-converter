"""Savings / ROI service — the migration business case for an uploaded estate.

Deterministic and offline: runs the same ``BatchAnalyzer`` the profiler/portfolio
surfaces use, then applies the :class:`~a2d.savings.SavingsCalculator` so the
``a2d savings`` CLI command and the App report identical numbers.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from a2d.analyzer.batch import BatchAnalyzer
from a2d.savings import CostAssumptions, SavingsCalculator
from server.utils.package import materialize_uploads

logger = logging.getLogger("a2d.server.services.savings")


def estimate_savings(files: list[tuple[str, bytes]], overrides: dict | None = None) -> dict:
    """Estimate savings for uploaded workflows and return the report dict.

    ``overrides`` is an optional mapping of cost-assumption overrides (same shape as
    the CLI ``--config`` file), merged over the defaults. Raises :class:`ValueError`
    when nothing usable was supplied or an override is invalid, so the router can
    answer 4xx. ``.yxzp`` packages are unzipped first.
    """
    if not files:
        raise ValueError("at least one workflow file is required")

    assumptions = CostAssumptions.from_mapping(overrides) if overrides else CostAssumptions.default()

    skipped: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = materialize_uploads(files, Path(tmpdir), skipped=skipped)
        analyses = BatchAnalyzer(expand_macros=True).analyze_files(paths)

    if not analyses:
        raise ValueError("no workflows could be analyzed")

    report = SavingsCalculator().compute(analyses, assumptions)

    logger.info(
        "Savings estimate: %d workflow(s), net annual=%.0f %s, skipped=%d",
        report.estate.workflow_count,
        report.net_annual_savings,
        report.currency,
        len(skipped),
    )
    result = report.to_dict()
    result["skipped_files"] = skipped
    return result
