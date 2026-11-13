"""Tests for review-session models and status classification."""

from __future__ import annotations

import pytest

from a2d.ir.nodes import FilterNode, UnsupportedNode
from a2d.review.models import (
    ReviewNode,
    ReviewSession,
    node_confidence,
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

    def test_a_todo_left_in_the_code_needs_review_even_without_a_warning(self):
        node = FilterNode(node_id=1, expression="[x]>0", conversion_confidence=1.0)
        code = "# Step 1: Filter\n# TODO: replace F.lit(True) with the real condition\ndf_1 = df_0.filter(F.lit(True))"
        assert node_review_status(node, [], code) == "needs_review"


class TestNodeConfidence:
    def test_finished_step_shows_mapping_confidence(self):
        node = FilterNode(node_id=1, expression="[x]>0", conversion_confidence=0.9)
        assert node_confidence(node, "df_1 = df_0.filter(F.col('x') > 0)") == 0.9

    @pytest.mark.parametrize(
        "code",
        [
            "# TODO: Join node 25 has no join keys\ndf_25 = df_10.join(df_18, F.lit(True))",
            "df_24 = None  # PLACEHOLDER - replace with Excel read",
            "# CANNOT CONVERT: Join node 3 has no right input connected.",
        ],
    )
    def test_unfinished_step_is_not_shown_as_confident(self, code):
        node = FilterNode(node_id=1, expression="[x]>0", conversion_confidence=1.0)
        assert node_confidence(node, code) == 0.0

    def test_unsupported_tool_has_no_confidence(self):
        assert node_confidence(UnsupportedNode(node_id=1, original_tool_type="Weird"), "") == 0.0


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


def test_real_unfinished_step_is_flagged_and_not_confident():
    """Make_Columns step 24 is an Excel Input the converter leaves as a PLACEHOLDER."""
    import logging
    from pathlib import Path

    from a2d.config import ConversionConfig
    from a2d.parser.workflow_parser import WorkflowParser
    from a2d.pipeline import ConversionPipeline
    from a2d.review.builder import build_review_session

    logging.disable(logging.WARNING)
    try:
        path = Path(__file__).parents[2] / "fixtures" / "packt" / "Make_Columns_Fix_for_Excel_data.yxmd"
        dag = ConversionPipeline(ConversionConfig()).build_dag(WorkflowParser().parse(path))
        node = next(n for n in build_review_session(dag, path.stem).nodes if n.node_id == 24)
    finally:
        logging.disable(logging.NOTSET)
    assert "PLACEHOLDER" in node.generated_code
    assert node.status == "needs_review"
    assert node.confidence == 0.0
    assert node.to_dict()["unfinished"] is True
