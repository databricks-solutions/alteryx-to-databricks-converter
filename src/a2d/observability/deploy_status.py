"""Pure decision function for the headline "deploy readiness" banner.

Python port of ``frontend/src/lib/deploy-status.ts``. The CLI calls
:func:`derive_deploy_status` to print the same three-tier banner the UI
shows, so users get parity messaging in the terminal.

Rule table::

    +-----------------+--------------------------------------------------------+
    | "ready"         | ALL of:                                                |
    |                 |   - every requested format reports status="success"    |
    |                 |   - best-format coverage >= 95 %                       |
    |                 |   - best-format confidence >= 80 / 100                 |
    |                 |   - zero "Unsupported node ..." warnings               |
    |                 |   - zero "No <X> generator for ..." warnings           |
    +-----------------+--------------------------------------------------------+
    | "needs_review"  | Generator(s) succeeded, BUT at least one of:           |
    |                 |   - any missing-visitor / expression-fallback warning  |
    |                 |   - 60 <= confidence < 80                              |
    |                 |   - 70 <= coverage < 95                                |
    |                 | AND we don't already qualify for "cannot_deploy".      |
    +-----------------+--------------------------------------------------------+
    | "cannot_deploy" | ANY of:                                                |
    |                 |   - any format with status="failed"                    |
    |                 |   - best-format coverage < 70 %                        |
    |                 |   - an unsupported node sits in a disconnected         |
    |                 |     component (i.e. it actually breaks the dataflow)   |
    +-----------------+--------------------------------------------------------+
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal

from a2d.observability.warning_categorization import (
    categorize_for_format,
    nodes_in_broken_components,
    parse_warnings,
)

DeployStatus = Literal["ready", "needs_review", "cannot_deploy"]

# ── Threshold constants ────────────────────────────────────────────────────
#: Inclusive minimum coverage % for "ready".
READY_COVERAGE: float = 95.0
#: Inclusive minimum confidence (out of 100) for "ready".
READY_CONFIDENCE: float = 80.0
#: Inclusive minimum coverage % to stay above "cannot_deploy".
REVIEW_COVERAGE_MIN: float = 70.0
#: Inclusive minimum confidence (out of 100) to stay above the lower band.
REVIEW_CONFIDENCE_MIN: float = 60.0


# Single-letter alias dict so callers can grep for thresholds in one place.
DEPLOY_THRESHOLDS: dict[str, float] = {
    "READY_COVERAGE": READY_COVERAGE,
    "READY_CONFIDENCE": READY_CONFIDENCE,
    "REVIEW_COVERAGE_MIN": REVIEW_COVERAGE_MIN,
    "REVIEW_CONFIDENCE_MIN": REVIEW_CONFIDENCE_MIN,
}


def derive_deploy_status(
    *,
    coverage: float | None,
    confidence: float | None,
    formats_status: Mapping[str, str],
    workflow_warnings: Iterable[str],
    best_format_warnings: Iterable[str],
    best_format: str | None,
) -> DeployStatus:
    """Return the deploy-readiness tier for a multi-format conversion result.

    Args:
        coverage: Coverage percentage of the best format (0-100, ``None`` if
            unavailable).
        confidence: Confidence score of the best format (0-100, ``None`` if
            unavailable).
        formats_status: Mapping from format id ("pyspark", "dlt", ...) to its
            status string. Anything that isn't ``"success"`` is treated as a
            failure for "any format failed?" purposes.
        workflow_warnings: Workflow-level warnings (DAG validation, parser
            issues — these contain the ``Unsupported node ...`` and
            ``Graph has N disconnected ...`` strings).
        best_format_warnings: Warnings emitted while generating the best
            format (these contain the ``No <X> generator for ...`` and
            expression-fallback strings).
        best_format: The id of the best format, or ``None`` when every
            generator failed.

    The keyword-only signature matches the TS shape (which receives a single
    ``ConversionResult`` object) but is decoupled from the Python pipeline
    types so this function stays unit-testable in isolation.
    """
    # 1. Cannot deploy: any format outright failed.
    if any(status != "success" for status in formats_status.values()):
        return "cannot_deploy"
    if not formats_status:
        # Nothing was even attempted — that's effectively "every format failed".
        return "cannot_deploy"

    # 2. Cannot deploy: an unsupported node sits in a broken component.
    parsed_workflow = parse_warnings(list(workflow_warnings))
    if nodes_in_broken_components(parsed_workflow):
        return "cannot_deploy"

    # No best format / its slot is missing → every generator must have failed.
    if not best_format or best_format not in formats_status:
        return "cannot_deploy"
    if formats_status[best_format] != "success":
        return "cannot_deploy"

    # 3. Cannot deploy: coverage too low.
    if coverage is not None and coverage < REVIEW_COVERAGE_MIN:
        return "cannot_deploy"

    # 4. Combine workflow + best-format warnings, count categories.
    cats = categorize_for_format(workflow_warnings, best_format_warnings)
    has_manual_work = bool(cats.unsupported) or bool(cats.review)

    # 5. Ready: clean, high-coverage, high-confidence.
    if (
        not has_manual_work
        and coverage is not None
        and coverage >= READY_COVERAGE
        and confidence is not None
        and confidence >= READY_CONFIDENCE
    ):
        return "ready"

    # 6. Otherwise: needs review.
    return "needs_review"


def deploy_status_explanation(status: DeployStatus) -> str:
    """One-line plain-English explanation matching the UI copy."""
    if status == "ready":
        return (
            "Coverage and confidence both meet the bar; no manual review "
            "warnings. You can deploy the generated code as-is."
        )
    if status == "needs_review":
        return (
            "Generation succeeded, but some nodes need a human pass before "
            "deploying — see the categorized warnings below."
        )
    return (
        "Generated code can't be deployed without changes. Either a format "
        "failed, coverage is below 70%, or an unsupported node breaks the "
        "main dataflow."
    )
