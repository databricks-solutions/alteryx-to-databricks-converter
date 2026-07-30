"""Golden-fixture equivalence tests — real workflows vs. committed expected CSV.

These exercise the full ``verify_workflow`` path (parse → reference execute →
parity) against ground-truth output captured from the workflow's known
semantics, so a regression in any core operator is caught end-to-end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from a2d.verification.runner import verify_workflow

WORKFLOWS = Path(__file__).parent.parent.parent / "fixtures" / "workflows"
EXPECTED = Path(__file__).parent.parent.parent / "fixtures" / "expected_outputs"


class TestGoldenFixtures:
    def test_simple_filter_matches_golden(self):
        expected = pd.read_csv(EXPECTED / "simple_filter_expected.csv")
        result = verify_workflow(
            WORKFLOWS / "simple_filter.yxmd",
            source_data={},  # embedded TextInput data
            expected_output=expected,
            use_spark=False,
        )
        assert result.status == "pass", result.to_dict()
        assert result.mode == "golden"
        assert result.parity is not None and result.parity.passed

    def test_simple_filter_detects_regression(self):
        # A deliberately wrong golden must fail — proves the check has teeth.
        wrong = pd.DataFrame({"Name": ["Alice"], "Age": [30], "City": ["Toronto"]})
        result = verify_workflow(
            WORKFLOWS / "simple_filter.yxmd",
            source_data={},
            expected_output=wrong,
            use_spark=False,
        )
        assert result.status == "fail"
