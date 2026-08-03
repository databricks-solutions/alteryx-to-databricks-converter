"""Tests for the store-backed LearnedClient proposer."""

from __future__ import annotations

import pandas as pd

from a2d.feedback.client import LearnedClient
from a2d.feedback.store import FeedbackStore
from a2d.llm.assist import LLMAssistedConverter
from a2d.llm.models import ConversionCandidate, ConversionRequest, ProposedNode

RENAME_CFG = {"Fields": {"Field": [{"@field": "old_a", "@rename": "new_a"}]}}


def _select_passthrough():
    return ConversionCandidate(
        nodes=[ProposedNode(ref="n0", kind="SelectNode", params={"select_all_unknown": True})],
        output_ref="n0",
    )


class TestLearnedClient:
    def test_proposes_learned_first(self, tmp_path):
        store = FeedbackStore(tmp_path / "fb.json")
        store.record("Message", {"Text": "x"}, _select_passthrough(), source="verified")

        client = LearnedClient(store=FeedbackStore(tmp_path / "fb.json"))
        req = ConversionRequest(tool_type="Message", plugin_name="p", configuration={"Text": "y"})
        candidates = client.propose(req)
        assert candidates[0].source == "learned"

    def test_falls_back_to_stub_for_unknown(self, tmp_path):
        client = LearnedClient(store=FeedbackStore(tmp_path / "fb.json"))
        # Empty store → Message handled by the stub fallback.
        req = ConversionRequest(tool_type="Message", plugin_name="p", configuration={})
        candidates = client.propose(req)
        assert candidates
        assert candidates[0].source == "stub"

    def test_no_candidate_when_neither_knows(self, tmp_path):
        client = LearnedClient(store=FeedbackStore(tmp_path / "fb.json"))
        req = ConversionRequest(tool_type="ExoticUnknownTool", plugin_name="p", configuration={})
        assert client.propose(req) == []


class TestLearnLoopEndToEnd:
    def test_verify_record_replay_reverify(self, tmp_path):
        store_path = tmp_path / "fb.json"
        cfg = RENAME_CFG
        req = ConversionRequest(tool_type="DynamicRename", plugin_name="p", configuration=cfg, node_id=1)
        sample = pd.DataFrame({"old_a": [1, 2], "b": [3, 4]})
        expected = sample.rename(columns={"old_a": "new_a"})

        # 1. Verify a fresh proposal, then record it.
        out = LLMAssistedConverter().assist(req, sample_input=sample, expected_output=expected)
        assert out.accepted
        FeedbackStore(store_path).record("DynamicRename", cfg, out.candidate, source="verified")

        # 2. A LearnedClient now proposes it first, and it re-passes the gate.
        client = LearnedClient(store=FeedbackStore(store_path))
        out2 = LLMAssistedConverter(client=client).assist(req, sample_input=sample, expected_output=expected)
        assert out2.accepted
        assert out2.candidate.source == "learned"

    def test_stale_learned_mapping_is_rejected_by_gate(self, tmp_path):
        """A learned mapping that no longer reproduces the golden is caught."""
        store_path = tmp_path / "fb.json"
        # Record a pass-through mapping for a tool.
        FeedbackStore(store_path).record("WeirdTool", {"k": 1}, _select_passthrough(), source="verified")

        client = LearnedClient(store=FeedbackStore(store_path))
        req = ConversionRequest(tool_type="WeirdTool", plugin_name="p", configuration={"k": 2}, node_id=1)
        sample = pd.DataFrame({"a": [1, 2]})
        # Golden that a pass-through cannot produce → gate must reject.
        wrong = pd.DataFrame({"a": [99, 99]})
        out = LLMAssistedConverter(client=client).assist(req, sample_input=sample, expected_output=wrong)
        assert not out.accepted
        assert out.verdict.status == "rejected"
