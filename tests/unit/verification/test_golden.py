"""Golden-fixture equivalence tests — real workflows vs. committed expected CSV.

These exercise the full ``verify_workflow`` path (parse → reference execute →
parity) against ground-truth output captured from each workflow's known
semantics, so a regression in any core operator is caught end-to-end. Each
fixture below targets a distinct operator path (filter fan-out, join+summarize,
formula+filter+sort) so the suite has real breadth, not a single case.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from a2d.verification.runner import verify_workflow

WORKFLOWS = Path(__file__).parent.parent.parent / "fixtures" / "workflows"
EXPECTED = Path(__file__).parent.parent.parent / "fixtures" / "expected_outputs"

# (workflow file, golden CSV, what operator path it exercises)
GOLDEN_CASES = [
    ("simple_filter.yxmd", "simple_filter_expected.csv", "filter True branch"),
    ("join_and_summarize.yxmd", "join_and_summarize_expected.csv", "join + summarize"),
    ("formula_filter_sort.yxmd", "formula_filter_sort_expected.csv", "formula + filter + sort"),
]


class TestGoldenFixtures:
    @pytest.mark.parametrize(("workflow", "golden", "desc"), GOLDEN_CASES)
    def test_matches_golden(self, workflow: str, golden: str, desc: str):
        expected = pd.read_csv(EXPECTED / golden)
        result = verify_workflow(
            WORKFLOWS / workflow,
            source_data={},  # all use embedded TextInput data
            expected_output=expected,
            use_spark=False,
        )
        assert result.status == "pass", f"{desc}: {result.to_dict()}"
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

    def test_join_summarize_wrong_aggregate_fails(self):
        # Wrong aggregate value must be caught.
        wrong = pd.DataFrame({"Region": ["East", "West"], "Total_Amount": [999.0, 200.0], "Order_Count": [3, 1]})
        result = verify_workflow(
            WORKFLOWS / "join_and_summarize.yxmd",
            source_data={},
            expected_output=wrong,
            use_spark=False,
        )
        assert result.status == "fail"
