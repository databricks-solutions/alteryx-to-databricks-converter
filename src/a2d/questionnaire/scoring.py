"""Deterministic scoring for the readiness questionnaire.

Given a mapping of ``{question_id: option_value}``, roll up per-dimension and
overall 0-100 scores, resolve a tier, and collect the tips attached to the gap
answers. No model, no randomness: identical answers always score identically.
"""

from __future__ import annotations

from a2d.questionnaire.bank import DIMENSIONS, QUESTION_BANK, question_index
from a2d.questionnaire.model import QuestionnaireConfig, ReadinessResult


def blank_answers() -> dict[str, str]:
    """A template mapping every question id to an empty answer (for scaffolding)."""
    return {q.id: "" for q in QUESTION_BANK}


def score(answers: dict[str, str], config: QuestionnaireConfig | None = None) -> ReadinessResult:
    """Score a set of answers into a :class:`ReadinessResult`.

    ``answers`` maps question id → chosen option value; missing or empty values are
    treated as unanswered (they don't score and are reported). An unknown question
    id, or an option value that doesn't belong to its question, raises
    :class:`ValueError` so the CLI/API can answer 4xx rather than scoring garbage.
    """
    cfg = config or QuestionnaireConfig.default()
    if not isinstance(answers, dict):
        raise ValueError("answers must be a mapping of question_id -> option_value")

    index = question_index()
    unknown = set(answers) - set(index)
    if unknown:
        raise ValueError(f"unknown question id(s): {sorted(unknown)}")

    # Accumulate weighted score + weight per dimension over answered questions.
    dim_weighted: dict[str, float] = {dim: 0.0 for dim in DIMENSIONS}
    dim_weight: dict[str, float] = {dim: 0.0 for dim in DIMENSIONS}
    tips: list[dict] = []
    unanswered: list[str] = []
    answered = 0

    for q in QUESTION_BANK:
        raw = answers.get(q.id)
        if raw is None or raw == "":
            unanswered.append(q.id)
            continue
        opt = q.option(raw)
        if opt is None:
            valid = ", ".join(o.value for o in q.options)
            raise ValueError(f"invalid answer {raw!r} for question {q.id!r}; valid: {valid}")

        answered += 1
        dim_weighted[q.dimension] += opt.score * q.weight
        dim_weight[q.dimension] += q.weight

        if opt.tip and opt.score < cfg.tip_score_threshold:
            tips.append(
                {
                    "question_id": q.id,
                    "dimension": q.dimension,
                    "dimension_label": DIMENSIONS.get(q.dimension, q.dimension),
                    "prompt": q.prompt,
                    "answer": opt.label,
                    "score": opt.score,
                    "tip": opt.tip,
                }
            )

    # Per-dimension scores (only for dimensions with at least one answer).
    dimension_scores: dict[str, float] = {}
    for dim in DIMENSIONS:
        if dim_weight[dim] > 0:
            dimension_scores[dim] = dim_weighted[dim] / dim_weight[dim]

    # Overall = dimension scores weighted by configured dimension weights.
    num = 0.0
    den = 0.0
    for dim, dscore in dimension_scores.items():
        w = cfg.dimension_weights.get(dim, 1.0)
        num += dscore * w
        den += w
    overall = (num / den) if den > 0 else 0.0

    tips.sort(key=lambda t: t["score"])

    return ReadinessResult(
        overall_score=overall,
        tier=cfg.tier_for(overall),
        dimension_scores=dimension_scores,
        dimension_labels=dict(DIMENSIONS),
        tips=tips,
        answered=answered,
        total_questions=len(QUESTION_BANK),
        unanswered=unanswered,
    )
