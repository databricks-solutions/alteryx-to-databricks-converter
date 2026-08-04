"""Python half of the cross-language warning/deploy-status contract.

The same rules exist twice — here and in ``frontend/src/lib/`` — so the CLI and
the web UI agree on what a conversion means. These tests and their TypeScript
counterpart (``frontend/src/lib/__tests__/shared-contract.test.ts``) assert
against the SAME fixture, so changing one implementation without the other fails
the other language's suite instead of silently disagreeing in front of a user.

Fixture: ``tests/fixtures/shared/warning_parsing_cases.json``
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from a2d.observability.deploy_status import derive_deploy_status
from a2d.observability.warning_categorization import parse_warning

FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "shared" / "warning_parsing_cases.json"


def _cases() -> dict:
    return json.loads(FIXTURE.read_text())


WARNING_CASES = _cases()["warning_cases"]
DEPLOY_CASES = _cases()["deploy_status_cases"]


class TestWarningParsingContract:
    @pytest.mark.parametrize("case", WARNING_CASES, ids=lambda c: c["name"])
    def test_parsed_warning_matches_shared_fixture(self, case):
        parsed = parse_warning(case["raw"])
        expected = case["expect"]

        assert parsed.kind == expected["kind"], f"{case['name']}: kind"
        assert parsed.severity == expected["severity"], f"{case['name']}: severity"
        if "node_id" in expected:
            assert parsed.node_id == expected["node_id"], f"{case['name']}: node_id"
        if "tool" in expected:
            assert parsed.tool == expected["tool"], f"{case['name']}: tool"


class TestDeployStatusContract:
    @pytest.mark.parametrize("case", DEPLOY_CASES, ids=lambda c: c["name"])
    def test_deploy_status_matches_shared_fixture(self, case):
        status = derive_deploy_status(
            coverage=case["coverage"],
            confidence=case["confidence"],
            formats_status=case["formats_status"],
            workflow_warnings=case["workflow_warnings"],
            best_format_warnings=case["best_format_warnings"],
            best_format="pyspark",
        )
        assert status == case["expect"], f"{case['name']}: expected {case['expect']}, got {status}"


class TestFixtureIsUsable:
    """Guard the guard: an empty or unreadable fixture must fail loudly."""

    def test_fixture_has_cases(self):
        assert len(WARNING_CASES) >= 5
        assert len(DEPLOY_CASES) >= 5

    def test_every_case_is_named(self):
        for case in [*WARNING_CASES, *DEPLOY_CASES]:
            assert case.get("name"), f"unnamed case: {case}"
