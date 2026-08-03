"""Tests for the propose→build→verify gate — the core safety property."""

from __future__ import annotations

import pandas as pd

from a2d.llm.assist import LLMAssistedConverter
from a2d.llm.client import StubLLMClient
from a2d.llm.models import ConversionCandidate, ConversionRequest, ProposedNode

RENAME_CFG = {"Fields": {"Field": [{"@field": "old_a", "@rename": "new_a"}]}}


def _rename_request():
    return ConversionRequest(tool_type="DynamicRename", plugin_name="p", configuration=RENAME_CFG, node_id=42)


class TestGate:
    def test_verified_when_candidate_matches_golden(self):
        sample = pd.DataFrame({"old_a": [1, 2, 3], "b": [4, 5, 6]})
        expected = sample.rename(columns={"old_a": "new_a"})
        out = LLMAssistedConverter().assist(_rename_request(), sample_input=sample, expected_output=expected)
        assert out.accepted
        assert out.verdict.status == "verified"
        assert out.verdict.parity_score == 1.0
        assert out.output_node_id is not None
        assert out.dag is not None

    def test_rejected_when_output_differs(self):
        sample = pd.DataFrame({"old_a": [1, 2, 3], "b": [4, 5, 6]})
        wrong = pd.DataFrame({"new_a": [9, 9, 9], "b": [4, 5, 6]})
        out = LLMAssistedConverter().assist(_rename_request(), sample_input=sample, expected_output=wrong)
        assert not out.accepted
        assert out.verdict.status == "rejected"

    def test_unverified_without_golden(self):
        sample = pd.DataFrame({"old_a": [1], "b": [2]})
        out = LLMAssistedConverter().assist(_rename_request(), sample_input=sample)
        assert not out.accepted
        assert out.verdict.status == "unverified"

    def test_unverified_without_any_sample(self):
        out = LLMAssistedConverter().assist(_rename_request())
        assert out.verdict.status == "unverified"

    def test_no_candidate_for_unknown_tool(self):
        req = ConversionRequest(tool_type="ExoticTool", plugin_name="p", configuration={}, node_id=1)
        out = LLMAssistedConverter().assist(req)
        assert out.candidate is None
        assert out.verdict is None
        assert out.considered == 0


class _CyclicClient(StubLLMClient):
    """Returns a structurally invalid candidate (a self-cycle) to test build guards."""

    def propose(self, request, *, max_candidates=3):
        return [
            ConversionCandidate(
                nodes=[ProposedNode(ref="a", kind="FilterNode", params={"expression": "[x]>0"}, inputs=["a"])],
                output_ref="a",
            )
        ]


class _BadRefClient(StubLLMClient):
    def propose(self, request, *, max_candidates=3):
        return [
            ConversionCandidate(
                nodes=[ProposedNode(ref="a", kind="FilterNode", params={"expression": "[x]>0"})],
                output_ref="does_not_exist",
            )
        ]


class TestBuildGuards:
    def test_cyclic_candidate_discarded(self):
        req = ConversionRequest(tool_type="Anything", plugin_name="p", configuration={}, node_id=1)
        out = LLMAssistedConverter(client=_CyclicClient()).assist(req)
        # Candidate failed to build → no usable candidate returned.
        assert out.candidate is None
        assert "failed to build" in " ".join(out.notes)

    def test_bad_output_ref_discarded(self):
        req = ConversionRequest(tool_type="Anything", plugin_name="p", configuration={}, node_id=1)
        out = LLMAssistedConverter(client=_BadRefClient()).assist(req)
        assert out.candidate is None
