"""Tests for the offline stub LLM client and its knowledge base."""

from __future__ import annotations

from a2d.llm.client import StubLLMClient, get_default_client
from a2d.llm.models import ConversionCandidate, ConversionRequest


class TestStubClient:
    def test_default_client_is_stub(self):
        assert isinstance(get_default_client(), StubLLMClient)

    def test_known_tool_types(self):
        known = StubLLMClient().known_tool_types
        assert {"Message", "Test", "DynamicRename"} <= known

    def test_message_proposes_passthrough_select(self):
        req = ConversionRequest(tool_type="Message", plugin_name="p", configuration={})
        candidates = StubLLMClient().propose(req)
        assert len(candidates) == 1
        cand = candidates[0]
        assert isinstance(cand, ConversionCandidate)
        assert [n.kind for n in cand.nodes] == ["SelectNode"]
        assert cand.output_ref == cand.nodes[0].ref

    def test_unknown_tool_returns_no_candidate(self):
        req = ConversionRequest(tool_type="SomeExoticTool", plugin_name="p", configuration={})
        assert StubLLMClient().propose(req) == []

    def test_dynamic_rename_with_explicit_map(self):
        cfg = {"Fields": {"Field": [{"@field": "a", "@rename": "b"}]}}
        req = ConversionRequest(tool_type="DynamicRename", plugin_name="p", configuration=cfg)
        candidates = StubLLMClient().propose(req)
        assert len(candidates) == 1
        ops = candidates[0].nodes[0].params["field_operations"]
        assert ops[0]["field_name"] == "a"
        assert ops[0]["rename_to"] == "b"

    def test_dynamic_rename_without_map_returns_nothing(self):
        req = ConversionRequest(tool_type="DynamicRename", plugin_name="p", configuration={})
        assert StubLLMClient().propose(req) == []

    def test_max_candidates_caps_results(self):
        req = ConversionRequest(tool_type="Message", plugin_name="p", configuration={})
        assert len(StubLLMClient().propose(req, max_candidates=0)) == 0
