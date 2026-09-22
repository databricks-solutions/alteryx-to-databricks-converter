"""Unit tests for the migration-readiness questionnaire (deterministic scoring)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from a2d.questionnaire import (
    DIMENSIONS,
    QUESTION_BANK,
    QuestionnaireConfig,
    blank_answers,
    prefill_from_estate,
    score,
)

# ── bank integrity ──


def test_bank_ids_unique_and_dimensions_valid():
    ids = [q.id for q in QUESTION_BANK]
    assert len(ids) == len(set(ids)), "duplicate question ids"
    for q in QUESTION_BANK:
        assert q.dimension in DIMENSIONS
        assert q.options, f"{q.id} has no options"
        for opt in q.options:
            assert 0 <= opt.score <= 100


def test_every_dimension_has_questions():
    dims_with_q = {q.dimension for q in QUESTION_BANK}
    assert dims_with_q == set(DIMENSIONS)


def test_blank_answers_covers_all_questions():
    blank = blank_answers()
    assert set(blank) == {q.id for q in QUESTION_BANK}
    assert all(v == "" for v in blank.values())


# ── scoring ──


def test_score_all_top_answers_is_advanced():
    # Pick each question's highest-scoring option.
    answers = {q.id: max(q.options, key=lambda o: o.score).value for q in QUESTION_BANK}
    result = score(answers)
    assert result.answered == len(QUESTION_BANK)
    assert result.overall_score >= 80
    assert result.tier == "Advanced"
    assert result.tips == []  # top answers carry no gap tips


def test_score_all_worst_answers_is_not_ready():
    answers = {q.id: min(q.options, key=lambda o: o.score).value for q in QUESTION_BANK}
    result = score(answers)
    assert result.tier == "Not Ready"
    assert result.tips, "worst answers should surface tips"
    # tips are ordered weakest-first
    scores = [t["score"] for t in result.tips]
    assert scores == sorted(scores)


def test_partial_answers_only_score_answered():
    result = score({"estate_size": "small", "spark_sql": "strong"})
    assert result.answered == 2
    assert len(result.unanswered) == len(QUESTION_BANK) - 2
    # only the two answered dimensions get a score
    assert set(result.dimension_scores) == {"estate", "people"}


def test_unknown_question_raises():
    with pytest.raises(ValueError):
        score({"bogus_question": "x"})


def test_invalid_option_raises():
    with pytest.raises(ValueError):
        score({"estate_size": "nonexistent"})


def test_empty_answer_treated_as_unanswered():
    result = score({"estate_size": "", "spark_sql": "strong"})
    assert result.answered == 1
    assert "estate_size" in result.unanswered


# ── config ──


def test_dimension_weight_changes_overall():
    # Answer one strong governance q and one weak people q.
    answers = {"sponsorship": "strong", "spark_sql": "none"}
    base = score(answers).overall_score
    heavy_gov = score(answers, QuestionnaireConfig.from_mapping({"dimension_weights": {"governance": 5.0}}))
    assert heavy_gov.overall_score > base  # governance (strong) now dominates


def test_custom_tier_thresholds():
    cfg = QuestionnaireConfig.from_mapping(
        {"tiers": [{"name": "Go", "min_score": 50}, {"name": "Wait", "min_score": 0}]}
    )
    assert cfg.tier_for(75) == "Go"
    assert cfg.tier_for(20) == "Wait"


def test_tip_threshold_controls_tips():
    answers = {"data_volume": "large"}  # 'large' scores 65 with a tip
    # Default threshold 70 → tip shown; threshold 60 → suppressed.
    assert score(answers).tips
    assert score(answers, QuestionnaireConfig.from_mapping({"tip_score_threshold": 60})).tips == []


def test_config_rejects_unknown_dimension():
    with pytest.raises(ValueError):
        QuestionnaireConfig.from_mapping({"dimension_weights": {"nope": 1.0}})


def test_config_non_numeric_tier_raises_valueerror_not_typeerror():
    # A null/list min_score must map to a 4xx (ValueError), never a 500 (TypeError).
    with pytest.raises(ValueError):
        QuestionnaireConfig.from_mapping({"tiers": [{"name": "x", "min_score": None}]})
    with pytest.raises(ValueError):
        QuestionnaireConfig.from_mapping({"tip_score_threshold": [1, 2]})


def test_config_rejects_tiers_without_floor():
    # A custom tier list must include a floor (min_score <= 0), or a low score
    # would be misclassified into the lowest configured (non-floor) tier.
    with pytest.raises(ValueError):
        QuestionnaireConfig.from_mapping({"tiers": [{"name": "Ready", "min_score": 60}]})
    # With a floor it is accepted, and a below-bar score lands in the floor tier.
    cfg = QuestionnaireConfig.from_mapping(
        {"tiers": [{"name": "Ready", "min_score": 60}, {"name": "Not Ready", "min_score": 0}]}
    )
    assert cfg.tier_for(25) == "Not Ready"


def test_config_rejects_non_finite_weight():
    with pytest.raises(ValueError):
        QuestionnaireConfig.from_mapping({"dimension_weights": {"people": float("nan")}})


# ── prefill ──


def _wf(macros: bool, spatial: int, tools: set[str]):
    return SimpleNamespace(
        complexity=SimpleNamespace(has_macro_refs=macros, spatial_tool_count=spatial, level="Low"),
        coverage=SimpleNamespace(coverage_percentage=100.0, instance_coverage_percentage=100.0),
        node_count=5,
        tool_types_used=tools,
    )


def test_prefill_empty_estate():
    assert prefill_from_estate([]) == {}


def test_prefill_buckets_and_flags():
    # 3 clean workflows, no macros, no advanced tools.
    ans = prefill_from_estate([_wf(False, 0, {"Filter"})] * 3)
    assert ans["estate_size"] == "small"
    assert ans["macros"] == "none"
    assert ans["advanced_tools"] == "none"


def test_prefill_detects_heavy_tools():
    ans = prefill_from_estate([_wf(True, 0, {"PythonTool"})])
    assert ans["macros"] == "many"  # 1/1 uses macros
    assert ans["advanced_tools"] == "heavy"


def test_prefill_answers_are_scoreable():
    ans = prefill_from_estate([_wf(False, 1, {"Filter"})])
    # A spatial tool → "some"; result must score without error.
    result = score(ans)
    assert "estate" in result.dimension_scores
