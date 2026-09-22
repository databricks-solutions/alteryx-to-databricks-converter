"""Readiness-questionnaire service — score answers, prefill from an estate.

Deterministic and offline. Wraps :mod:`a2d.questionnaire` so the ``a2d readiness``
CLI and the App share one scoring path. Nothing is persisted.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from a2d.analyzer.batch import BatchAnalyzer
from a2d.questionnaire import (
    DIMENSIONS,
    QuestionnaireConfig,
    prefill_from_estate,
    questions_by_dimension,
    score,
)
from server.utils.package import materialize_uploads

logger = logging.getLogger("a2d.server.services.readiness")


def get_questions() -> dict:
    """Return the question bank (grouped by dimension) plus config defaults.

    The App renders the form from this, so it never hardcodes question content.
    """
    cfg = QuestionnaireConfig.default()
    grouped = questions_by_dimension()
    return {
        "dimensions": [
            {
                "id": dim,
                "label": label,
                "questions": [q.to_dict() for q in grouped.get(dim, [])],
            }
            for dim, label in DIMENSIONS.items()
        ],
        "config_defaults": cfg.to_dict(),
    }


def score_answers(answers: dict, config_overrides: dict | None = None) -> dict:
    """Score a set of answers and return the :class:`ReadinessResult` dict.

    Raises :class:`ValueError` for an unknown question id, an invalid option value,
    or a bad config override, so the router can answer 4xx.
    """
    cfg = QuestionnaireConfig.from_mapping(config_overrides) if config_overrides else QuestionnaireConfig.default()
    result = score(answers, cfg)
    logger.info(
        "Readiness scored: %.0f/100 (%s), %d/%d answered",
        result.overall_score,
        result.tier,
        result.answered,
        result.total_questions,
    )
    return result.to_dict()


def prefill_answers(files: list[tuple[str, bytes]]) -> dict:
    """Suggest estate answers from uploaded workflows. Returns ``{answers, skipped_files}``."""
    if not files:
        raise ValueError("at least one workflow file is required")

    skipped: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = materialize_uploads(files, Path(tmpdir), skipped=skipped)
        analyses = BatchAnalyzer().analyze_files(paths)

    if not analyses:
        raise ValueError("no workflows could be analyzed")

    suggested = prefill_from_estate(analyses)
    logger.info("Readiness prefill from %d workflow(s): %d answer(s)", len(analyses), len(suggested))
    return {"answers": suggested, "workflow_count": len(analyses), "skipped_files": skipped}
