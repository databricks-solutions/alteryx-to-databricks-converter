"""Tests for the macro expansion engine."""

from __future__ import annotations

from pathlib import Path

from a2d.config import ConversionConfig
from a2d.ir.nodes import UnsupportedNode
from a2d.macro.engine import MacroExpansionEngine
from a2d.parser.workflow_parser import WorkflowParser
from a2d.pipeline import ConversionPipeline

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "macro"


def _base(name):
    parser = WorkflowParser()
    parsed = parser.parse(FIXTURES / name)
    # Default config has expand_macros=False, so this is the un-expanded base.
    dag = ConversionPipeline(ConversionConfig())._build_dag(parsed)
    return parsed, dag


class TestExpansion:
    def test_call_node_replaced_by_interior(self):
        parsed, base = _base("parent_with_macro.yxmd")
        # Baseline: the macro call is an UnsupportedNode.
        assert any(isinstance(n, UnsupportedNode) for n in base.all_nodes())

        result = MacroExpansionEngine().expand(parsed, base)
        assert result.expanded_calls == 1
        assert result.macro_count == 1
        # No unsupported node remains; interior tools are present.
        types = {n.original_tool_type for n in result.dag.all_nodes()}
        assert "DataCleansing" in types
        assert "Formula" in types
        assert not any(isinstance(n, UnsupportedNode) for n in result.dag.all_nodes())

    def test_wiring_is_end_to_end(self):
        parsed, base = _base("parent_with_macro.yxmd")
        result = MacroExpansionEngine().expand(parsed, base)
        order = [n.original_tool_type for n in result.dag.topological_order()]
        # Read -> (macro interior) -> Write, all in one connected chain.
        assert order[0] == "Input"
        assert order[-1] == "Output"
        assert result.dag.validate() == []  # no cycles / disconnected components

    def test_definition_metadata(self):
        parsed, base = _base("parent_with_macro.yxmd")
        result = MacroExpansionEngine().expand(parsed, base)
        defn = result.definitions[0]
        assert defn.function_name == "macro_standardcleanse"
        assert len(defn.inputs) == 1
        assert len(defn.outputs) == 1
        assert defn.interior_node_count == 2

    def test_base_dag_not_mutated(self):
        parsed, base = _base("parent_with_macro.yxmd")
        before = base.node_count
        MacroExpansionEngine().expand(parsed, base)
        assert base.node_count == before

    def test_definition_cached_across_calls(self):
        parsed, base = _base("parent_with_macro.yxmd")
        engine = MacroExpansionEngine()
        engine.expand(parsed, base)
        # Second expand reuses the cached definition (same object).
        first = engine._defn_cache["macros/standardcleanse.yxmc"]
        engine.expand(parsed, base)
        assert engine._defn_cache["macros/standardcleanse.yxmc"] is first


class TestUnresolved:
    def test_missing_macro_left_in_place(self):
        parsed, base = _base("parent_missing_macro.yxmd")
        result = MacroExpansionEngine().expand(parsed, base)
        assert result.expanded_calls == 0
        assert len(result.unresolved) == 1
        assert result.unresolved[0].macro_path == "macros/DoesNotExist.yxmc"
        # The unsupported call node is preserved so manual conversion still works.
        assert any(isinstance(n, UnsupportedNode) for n in result.dag.all_nodes())

    def test_no_macro_calls_is_noop(self):
        parser = WorkflowParser()
        wf_dir = Path(__file__).parent.parent.parent / "fixtures" / "workflows"
        parsed = parser.parse(wf_dir / "simple_filter.yxmd")
        base = ConversionPipeline(ConversionConfig())._build_dag(parsed)
        result = MacroExpansionEngine().expand(parsed, base)
        assert result.expanded_calls == 0
        assert result.macro_count == 0
        assert result.dag.node_count == base.node_count


class TestPipelineIntegration:
    def test_expand_macros_flag_lifts_coverage(self):
        cfg_off = ConversionConfig(expand_macros=False)
        cfg_on = ConversionConfig(expand_macros=True)
        parser = WorkflowParser()
        parsed = parser.parse(FIXTURES / "parent_with_macro.yxmd")

        dag_off = ConversionPipeline(cfg_off)._build_dag(parsed)
        dag_on = ConversionPipeline(cfg_on)._build_dag(parsed)

        assert any(isinstance(n, UnsupportedNode) for n in dag_off.all_nodes())
        assert not any(isinstance(n, UnsupportedNode) for n in dag_on.all_nodes())
