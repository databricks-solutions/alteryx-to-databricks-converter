"""Tests for the feedback store and learned-mapping models."""

from __future__ import annotations

from a2d.feedback.models import LearnedMapping, config_signature
from a2d.feedback.store import FeedbackStore, default_store_path
from a2d.llm.models import ConversionCandidate, ProposedNode


def _candidate():
    return ConversionCandidate(
        nodes=[ProposedNode(ref="n0", kind="SelectNode", params={"select_all_unknown": True})],
        output_ref="n0",
        rationale="pass-through",
    )


class TestConfigSignature:
    def test_stable_and_value_insensitive(self):
        a = config_signature("Message", {"Text": "hello"})
        b = config_signature("Message", {"Text": "world"})
        # Same key shape → same signature regardless of literal values.
        assert a == b

    def test_key_shape_changes_signature(self):
        a = config_signature("Message", {"Text": "x"})
        b = config_signature("Message", {"Other": "x"})
        assert a != b

    def test_tool_type_changes_signature(self):
        assert config_signature("Message", {"K": 1}) != config_signature("Test", {"K": 1})

    def test_order_insensitive(self):
        assert config_signature("T", {"a": 1, "b": 2}) == config_signature("T", {"b": 2, "a": 1})


class TestFeedbackStore:
    def test_record_and_get_roundtrip(self, tmp_path):
        store = FeedbackStore(tmp_path / "fb.json")
        cfg = {"Text": "hi"}
        store.record("Message", cfg, _candidate(), source="verified")

        # Fresh store reads it back from disk.
        store2 = FeedbackStore(tmp_path / "fb.json")
        mapping = store2.get("Message", {"Text": "different value"})  # same shape
        assert mapping is not None
        assert mapping.tool_type == "Message"
        assert mapping.uses == 1
        assert mapping.source == "verified"

    def test_record_increments_uses(self, tmp_path):
        store = FeedbackStore(tmp_path / "fb.json")
        store.record("Message", {"T": "a"}, _candidate())
        m = store.record("Message", {"T": "b"}, _candidate())  # same shape
        assert m.uses == 2
        assert store.stats().total_mappings == 1

    def test_missing_store_is_empty(self, tmp_path):
        store = FeedbackStore(tmp_path / "nope.json")
        assert store.all_mappings() == []
        assert store.get("Message", {}) is None

    def test_corrupt_store_is_ignored(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{ not valid json")
        store = FeedbackStore(path)
        assert store.all_mappings() == []  # does not raise

    def test_to_candidate_materialises(self, tmp_path):
        store = FeedbackStore(tmp_path / "fb.json")
        store.record("Message", {}, _candidate())
        mapping = store.get("Message", {})
        cand = mapping.to_candidate()
        assert cand.source == "learned"
        assert cand.nodes[0].kind == "SelectNode"

    def test_stats_by_tool(self, tmp_path):
        store = FeedbackStore(tmp_path / "fb.json")
        store.record("Message", {"a": 1}, _candidate())
        store.record("Test", {"b": 1}, _candidate())
        stats = store.stats()
        assert stats.total_mappings == 2
        assert stats.by_tool == {"Message": 1, "Test": 1}


class TestDefaultStorePath:
    def test_env_override(self, monkeypatch, tmp_path):
        target = tmp_path / "custom.json"
        monkeypatch.setenv("A2D_FEEDBACK_STORE", str(target))
        assert default_store_path() == target

    def test_default_location(self, monkeypatch):
        monkeypatch.delenv("A2D_FEEDBACK_STORE", raising=False)
        assert default_store_path().name == "feedback.json"


class TestLearnedMappingSerialization:
    def test_roundtrip(self):
        m = LearnedMapping(
            signature="sig",
            tool_type="Message",
            candidate_nodes=[ProposedNode(ref="n0", kind="SelectNode", params={"x": 1}, inputs=[])],
            output_ref="n0",
            uses=3,
        )
        restored = LearnedMapping.from_dict(m.to_dict())
        assert restored.signature == "sig"
        assert restored.uses == 3
        assert restored.candidate_nodes[0].kind == "SelectNode"
