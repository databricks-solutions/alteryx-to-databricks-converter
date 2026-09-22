"""Migration readiness questionnaire — a deterministic self-assessment.

A static, weighted, Alteryx→Databricks-centric survey that scores organizational
readiness across four dimensions (estate, people, platform, governance) and returns
tailored tips. Distinct from :mod:`a2d.analyzer.readiness`, which derives a
file-based readiness signal from parsed workflows; this one scores *human* answers.
No language model is involved.
"""

from __future__ import annotations

from a2d.questionnaire.bank import (
    DIMENSIONS,
    QUESTION_BANK,
    Option,
    Question,
    question_index,
    questions_by_dimension,
)
from a2d.questionnaire.model import (
    DEFAULT_TIERS,
    QuestionnaireConfig,
    ReadinessResult,
)
from a2d.questionnaire.prefill import prefill_from_estate
from a2d.questionnaire.scoring import blank_answers, score

__all__ = [
    "DEFAULT_TIERS",
    "DIMENSIONS",
    "QUESTION_BANK",
    "Option",
    "Question",
    "QuestionnaireConfig",
    "ReadinessResult",
    "blank_answers",
    "prefill_from_estate",
    "question_index",
    "questions_by_dimension",
    "score",
]
