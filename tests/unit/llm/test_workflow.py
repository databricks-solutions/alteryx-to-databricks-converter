"""Tests for workflow-level assist orchestration."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from a2d.llm.workflow import scan_workflow_file

ASSIST_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "assist"
MESSAGE_WF = ASSIST_FIXTURES / "message_passthrough.yxmd"


class TestScanWorkflow:
    def test_detects_unsupported_and_proposes(self):
        report = scan_workflow_file(MESSAGE_WF)
        assert report.unsupported_total == 1
        assert report.proposed == 1
        # No sample/golden → unverified, never auto-accepted.
        assert report.verified == 0
        assert report.unverified == 1

    def test_verifies_with_sample_and_golden(self):
        orders = pd.DataFrame({"order_id": [1, 2, 3], "amount": [100, 250, 75]})
        # Message is a pass-through, so golden for node 2 equals the input.
        report = scan_workflow_file(
            MESSAGE_WF,
            source_data={"data/orders.csv": orders},
            node_goldens={2: orders},
        )
        assert report.verified == 1
        assert report.unverified == 0
        outcome = report.outcomes[0]
        assert outcome.node_id == 2
        assert outcome.accepted

    def test_wrong_golden_is_not_accepted(self):
        orders = pd.DataFrame({"order_id": [1, 2, 3], "amount": [100, 250, 75]})
        wrong = pd.DataFrame({"order_id": [9], "amount": [9]})
        report = scan_workflow_file(
            MESSAGE_WF,
            source_data={"data/orders.csv": orders},
            node_goldens={2: wrong},
        )
        assert report.verified == 0
        assert report.outcomes[0].verdict.status == "rejected"
