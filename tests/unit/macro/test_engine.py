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


class TestResolvePathContainment:
    """Security: macro references are untrusted and must stay within trusted roots."""

    def test_absolute_path_outside_roots_rejected(self, tmp_path):
        # A macro living outside the workflow dir / search paths must not resolve,
        # even when addressed by absolute path.
        outside = tmp_path / "secret.yxmc"
        outside.write_text("<x/>", encoding="utf-8")
        workflow_dir = tmp_path / "wf"
        workflow_dir.mkdir()

        engine = MacroExpansionEngine()
        assert engine._resolve_path(str(outside), workflow_dir) is None

    def test_parent_traversal_rejected(self, tmp_path):
        outside = tmp_path / "secret.yxmc"
        outside.write_text("<x/>", encoding="utf-8")
        workflow_dir = tmp_path / "wf"
        workflow_dir.mkdir()

        engine = MacroExpansionEngine()
        assert engine._resolve_path("../secret.yxmc", workflow_dir) is None

    def test_relative_macro_within_root_resolves(self, tmp_path):
        workflow_dir = tmp_path / "wf"
        workflow_dir.mkdir()
        macro = workflow_dir / "helper.yxmc"
        macro.write_text("<x/>", encoding="utf-8")

        engine = MacroExpansionEngine()
        resolved = engine._resolve_path("helper.yxmc", workflow_dir)
        assert resolved == macro.resolve()

    def test_windows_backslash_macro_path_resolves(self, tmp_path):
        # Alteryx authored on Windows writes MacroPath with backslashes; the .yxzp
        # extracts the file under forward-slash names. The resolver must normalize
        # \\ -> / or the macro is never found on a Linux server (returns None ->
        # UnresolvedMacro -> node stays Unknown). Regression for the .yxzp report.
        nested = tmp_path / "wf" / "_externals" / "1"
        nested.mkdir(parents=True)
        macro = nested / "Excel Ingest to Output (With Test for Open Files).yxmc"
        macro.write_text("<x/>", encoding="utf-8")
        workflow_dir = tmp_path / "wf"

        engine = MacroExpansionEngine()
        win_path = r"_externals\1\Excel Ingest to Output (With Test for Open Files).yxmc"
        resolved = engine._resolve_path(win_path, workflow_dir)
        assert resolved == macro.resolve()

    def test_windows_backslash_traversal_still_rejected(self, tmp_path):
        # Normalizing separators must not weaken containment: a backslash path that
        # escapes the root is still rejected.
        (tmp_path / "secret.yxmc").write_text("<x/>", encoding="utf-8")
        workflow_dir = tmp_path / "wf"
        workflow_dir.mkdir()

        engine = MacroExpansionEngine()
        assert engine._resolve_path(r"..\secret.yxmc", workflow_dir) is None

    def test_symlink_escape_rejected(self, tmp_path):
        # An in-root symlink pointing outside the trusted root must not resolve:
        # containment is checked on the RESOLVED (symlink-followed) path.
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.yxmc"
        secret.write_text("<x/>", encoding="utf-8")
        workflow_dir = tmp_path / "wf"
        workflow_dir.mkdir()
        link = workflow_dir / "link.yxmc"
        try:
            link.symlink_to(secret)
        except (OSError, NotImplementedError):
            import pytest

            pytest.skip("symlinks not supported on this platform")

        engine = MacroExpansionEngine()
        assert engine._resolve_path("link.yxmc", workflow_dir) is None
