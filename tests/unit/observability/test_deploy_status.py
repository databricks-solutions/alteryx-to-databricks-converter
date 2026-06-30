"""Tests for ``a2d.observability.deploy_status``.

Mirrors ``frontend/src/lib/deploy-status.ts``. The boundary cases here come
straight from the doc-comment table at the top of that file.
"""

from __future__ import annotations

import pytest

from a2d.observability.deploy_status import (
    DEPLOY_THRESHOLDS,
    READY_CONFIDENCE,
    READY_COVERAGE,
    REVIEW_COVERAGE_MIN,
    deploy_status_explanation,
    derive_deploy_status,
)

ALL_OK = {"pyspark": "success", "dlt": "success", "sql": "success", "lakeflow": "success"}


def _call(
    *,
    coverage: float | None = 100.0,
    confidence: float | None = 95.0,
    formats_status: dict[str, str] | None = None,
    workflow_warnings: list[str] | None = None,
    best_format_warnings: list[str] | None = None,
    best_format: str | None = "pyspark",
):
    return derive_deploy_status(
        coverage=coverage,
        confidence=confidence,
        formats_status=formats_status if formats_status is not None else ALL_OK,
        workflow_warnings=workflow_warnings or [],
        best_format_warnings=best_format_warnings or [],
        best_format=best_format,
    )


class TestThresholds:
    def test_constants_match_ts(self) -> None:
        assert READY_COVERAGE == 95.0
        assert READY_CONFIDENCE == 80.0
        assert REVIEW_COVERAGE_MIN == 70.0

    def test_threshold_dict_is_consistent(self) -> None:
        assert DEPLOY_THRESHOLDS["READY_COVERAGE"] == READY_COVERAGE
        assert DEPLOY_THRESHOLDS["READY_CONFIDENCE"] == READY_CONFIDENCE
        assert DEPLOY_THRESHOLDS["REVIEW_COVERAGE_MIN"] == REVIEW_COVERAGE_MIN


class TestReadyCases:
    def test_all_clean_high_coverage_high_confidence(self) -> None:
        assert _call(coverage=100.0, confidence=95.0) == "ready"

    def test_exactly_at_thresholds(self) -> None:
        assert _call(coverage=95.0, confidence=80.0) == "ready"

    def test_coverage_just_below_drops_to_review(self) -> None:
        assert _call(coverage=94.9, confidence=80.0) == "needs_review"

    def test_confidence_just_below_drops_to_review(self) -> None:
        assert _call(coverage=95.0, confidence=79.9) == "needs_review"


class TestNeedsReviewCases:
    def test_missing_generator_warning(self) -> None:
        assert (
            _call(
                coverage=100.0,
                confidence=100.0,
                best_format_warnings=["No PySpark generator for FooNode (node 5)"],
            )
            == "needs_review"
        )

    def test_expression_fallback_warning(self) -> None:
        assert (
            _call(
                coverage=100.0,
                confidence=100.0,
                best_format_warnings=["Filter expression fallback for node 1"],
            )
            == "needs_review"
        )

    def test_coverage_70_inclusive_is_review(self) -> None:
        assert _call(coverage=70.0, confidence=95.0) == "needs_review"

    def test_low_confidence_alone_does_not_escalate_to_cannot_deploy(self) -> None:
        # Per the TS source: confidence below the lower band still surfaces as
        # needs_review unless something else escalates.
        assert _call(coverage=95.0, confidence=59.9) == "needs_review"

    def test_unsupported_in_side_branch_is_review(self) -> None:
        # Unsupported node, but no disconnected-components warning ⇒ side-branch
        # interpretation never triggers cannot_deploy.
        assert (
            _call(
                coverage=95.0,
                confidence=95.0,
                workflow_warnings=["Unsupported node 5: No converter for tool type: Foo"],
            )
            == "needs_review"
        )


class TestCannotDeployCases:
    def test_any_format_failed(self) -> None:
        statuses = dict(ALL_OK)
        statuses["sql"] = "failed"
        assert _call(formats_status=statuses) == "cannot_deploy"

    def test_coverage_below_70(self) -> None:
        assert _call(coverage=69.9, confidence=100.0) == "cannot_deploy"

    def test_zero_coverage(self) -> None:
        assert _call(coverage=0.0, confidence=100.0) == "cannot_deploy"

    def test_unsupported_in_disconnected_component(self) -> None:
        # An unsupported node sitting in a disconnected component breaks the
        # main flow and escalates to cannot_deploy.
        assert (
            _call(
                coverage=100.0,
                confidence=100.0,
                workflow_warnings=[
                    "Unsupported node 765: No converter for tool type: Foo",
                    "Graph has 2 disconnected data components: [1, 2], [765, 833]",
                ],
            )
            == "cannot_deploy"
        )

    def test_no_best_format(self) -> None:
        # Empty formats means every generator failed.
        assert _call(formats_status={}, best_format=None) == "cannot_deploy"

    def test_best_format_not_in_formats(self) -> None:
        assert _call(formats_status={"pyspark": "success"}, best_format="dlt") == "cannot_deploy"


class TestExplanationCopy:
    @pytest.mark.parametrize("status", ["ready", "needs_review", "cannot_deploy"])
    def test_explanation_non_empty(self, status: str) -> None:
        assert deploy_status_explanation(status)  # type: ignore[arg-type]
        assert len(deploy_status_explanation(status)) > 20  # type: ignore[arg-type]
