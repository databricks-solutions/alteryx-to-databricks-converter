"""Designer generator: translation failures must be reported, bugs must surface.

These two fallbacks previously used a bare ``except Exception``, which treated a
genuine translator bug (``AttributeError``, ``TypeError``) exactly like an
unsupported expression: the filter case wrote the *original Alteryx expression*
into generated code and attached a generic warning. The result looked like a
successful conversion and failed later at runtime.

The contract now: catch only ``BaseTranslationError``, include the cause in the
warning so a reviewer knows what to fix, and let anything unexpected propagate.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from a2d.config import ConversionConfig
from a2d.generators.designer import DesignerGenerator
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import FilterNode, FormulaField, FormulaNode, ReadNode

# Unparseable in the expression engine (verified: raises ParserError/TokenizerError,
# both subclasses of BaseTranslationError).
UNPARSEABLE = "[a] > ((( "


@pytest.fixture
def generator() -> DesignerGenerator:
    return DesignerGenerator(ConversionConfig())


def _filter_dag(expression: str) -> WorkflowDAG:
    dag = WorkflowDAG()
    dag.add_node(ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv"))
    dag.add_node(FilterNode(node_id=2, expression=expression))
    dag.add_edge(1, 2)
    return dag


def _formula_dag(expression: str) -> WorkflowDAG:
    dag = WorkflowDAG()
    dag.add_node(ReadNode(node_id=1, file_path="/d/x.csv", file_format="csv"))
    dag.add_node(FormulaNode(node_id=2, formulas=[FormulaField("total", expression)]))
    dag.add_edge(1, 2)
    return dag


class TestTranslationFailureIsExplained:
    def test_filter_warning_includes_the_cause(self, generator):
        output = generator.generate(_filter_dag(UNPARSEABLE), "wf")
        joined = " ".join(output.warnings)

        assert "Designer filter expression fallback for node 2" in joined
        # The reason must be present — a bare "fallback" warning is not actionable.
        assert joined.strip() != "Designer filter expression fallback for node 2"
        assert len(joined) > len("Designer filter expression fallback for node 2: ")

    def test_formula_warning_includes_field_and_cause(self, generator):
        output = generator.generate(_formula_dag(UNPARSEABLE), "wf")
        joined = " ".join(output.warnings)

        assert "Designer formula fallback for total" in joined
        assert ":" in joined  # cause appended

    def test_valid_expressions_produce_no_fallback_warning(self, generator):
        output = generator.generate(_filter_dag("[amount] > 100"), "wf")

        assert not any("fallback" in w for w in output.warnings)


class TestUnexpectedErrorsPropagate:
    """A translator bug must not be silently absorbed as a "fallback"."""

    def test_filter_does_not_swallow_attribute_error(self, generator):
        with (
            patch.object(
                generator._sql._translator,
                "translate_string",
                side_effect=AttributeError("translator bug"),
            ),
            pytest.raises(AttributeError, match="translator bug"),
        ):
            generator.generate(_filter_dag("[amount] > 100"), "wf")

    def test_formula_does_not_swallow_type_error(self, generator):
        with (
            patch.object(
                generator._sql._translator,
                "translate_string",
                side_effect=TypeError("translator bug"),
            ),
            pytest.raises(TypeError, match="translator bug"),
        ):
            generator.generate(_formula_dag("[a] + [b]"), "wf")
