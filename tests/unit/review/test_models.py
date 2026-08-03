"""Tests for review-session models and status classification."""

from __future__ import annotations

import pytest

from a2d.ir.nodes import FilterNode, UnsupportedNode
from a2d.review.models import (
    ReviewNode,
    ReviewSession,
    node_review_status,
)


class TestNodeReviewStatus:
    def test_unsupported_is_cannot_convert(self):
        node = UnsupportedNode(node_id=1, original_tool_type="Weird")
        assert node_review_status(node, []) == "cannot_convert"

    def test_warnings_force_needs_review(self):
        node = FilterNode(node_id=1, expression="[x]>0", conversion_confidence=1.0)
        assert node_review_status(node, ["some warning"]) == "needs_review"

    def test_low_confidence_needs_review(self):
        node = FilterNode(node_id=1, expression="[x]>0", conversion_confidence=0.5)
        assert node_review_status(node, []) == "needs_review"

    def test_high_confidence_no_warnings_auto_accepted(self):
        node = FilterNode(node_id=1, expression="[x]>0", conversion_confidence=0.95)
        assert node_review_status(node, []) == "auto_accepted"


def _node(node_id, status, **kw):
    return ReviewNode(
        node_id=node_id,
        tool_type="T",
        annotation=None,
        position=(0, 0),
        status=status,
        confidence=1.0,
        generated_code="code",
        **kw,
    )


class TestReviewSession:
    def test_get_and_missing(self):
        s = ReviewSession("wf", "pyspark", nodes=[_node(1, "auto_accepted")])
        assert s.get(1).node_id == 1
        with pytest.raises(KeyError):
            s.get(999)

    def test_accept_reject_edit(self):
        s = ReviewSession("wf", "pyspark", nodes=[_node(1, "needs_review")])
        s.accept(1)
        assert s.get(1).decision == "accepted"
        s.reject(1)
        assert s.get(1).decision == "rejected"
        s.edit(1, "# custom")
        assert s.get(1).decision == "edited"
        assert s.get(1).effective_code == "# custom"

    def test_effective_code_defaults_to_generated(self):
        n = _node(1, "auto_accepted")
        assert n.effective_code == "code"

    def test_progress_counts(self):
        s = ReviewSession(
            "wf",
            "pyspark",
            nodes=[
                _node(1, "auto_accepted"),
                _node(2, "needs_review"),
                _node(3, "cannot_convert"),
            ],
        )
        assert s.total == 3
        assert s.needs_review_count == 2
        assert not s.is_complete  # node 2 and 3 unresolved

        s.accept(2)
        s.reject(3)
        assert s.resolved_count == 2
        assert s.is_complete  # all needs-review nodes decided

    def test_to_dict_shape(self):
        s = ReviewSession("wf", "sql", nodes=[_node(1, "auto_accepted")])
        d = s.to_dict()
        assert d["workflow_name"] == "wf"
        assert d["output_format"] == "sql"
        assert d["summary"]["total"] == 1
        assert d["nodes"][0]["node_id"] == 1
