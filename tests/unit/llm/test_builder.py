"""Tests for the candidate → IR builder allow-list."""

from __future__ import annotations

import pytest

from a2d.ir.nodes import FilterNode, FormulaNode, SelectNode
from a2d.llm.builder import ALLOWED_KINDS, CandidateBuildError, build_node


class TestAllowList:
    def test_allowed_kinds_are_safe_transform_nodes(self):
        assert set(ALLOWED_KINDS) == {"SelectNode", "FilterNode", "FormulaNode", "SortNode", "SampleNode"}

    def test_unknown_kind_rejected(self):
        with pytest.raises(CandidateBuildError, match="not in the allowed set"):
            build_node("WriteNode", 1, {})

    def test_arbitrary_string_rejected(self):
        with pytest.raises(CandidateBuildError):
            build_node("os.system", 1, {})


class TestBuilders:
    def test_build_filter(self):
        node = build_node("FilterNode", 5, {"expression": "[x] > 1"})
        assert isinstance(node, FilterNode)
        assert node.node_id == 5
        assert node.expression == "[x] > 1"
        assert node.conversion_method == "llm-assisted"

    def test_build_formula(self):
        node = build_node("FormulaNode", 6, {"formulas": [{"output_field": "y", "expression": "[x]*2"}]})
        assert isinstance(node, FormulaNode)
        assert node.formulas[0].output_field == "y"

    def test_build_select_rename(self):
        node = build_node(
            "SelectNode",
            7,
            {"field_operations": [{"field_name": "a", "action": "rename", "rename_to": "b"}]},
        )
        assert isinstance(node, SelectNode)
        assert node.field_operations[0].rename_to == "b"

    def test_malformed_formula_missing_key(self):
        with pytest.raises(CandidateBuildError, match="malformed params"):
            build_node("FormulaNode", 8, {"formulas": [{"expression": "no output field"}]})

    def test_malformed_select_op_not_dict(self):
        with pytest.raises(CandidateBuildError):
            build_node("SelectNode", 9, {"field_operations": ["not-a-dict"]})
