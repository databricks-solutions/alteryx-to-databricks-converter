"""Macro expansion across directories: nested macros, a macro that calls itself,
case-insensitive lookup, and a shared macro folder (``search_paths``)."""

from __future__ import annotations

from pathlib import Path

from a2d.config import ConversionConfig
from a2d.ir.nodes import UnsupportedNode
from a2d.macro.engine import MAX_NESTING_DEPTH, MacroExpansionEngine
from a2d.parser.workflow_parser import WorkflowParser
from a2d.pipeline import ConversionPipeline
from tests.unit.macro.builders import (
    BATCH,
    ITERATIVE,
    TAKES_SETTINGS,
    formula_macro,
    macro_calling,
    workflow_calling,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _expand(workflow: Path, search_paths: list[Path] | None = None):
    parsed = WorkflowParser().parse(workflow)
    base = ConversionPipeline(ConversionConfig())._build_dag(parsed)
    return MacroExpansionEngine(search_paths=search_paths).expand(parsed, base)


def _types(result) -> list[str]:
    return [n.original_tool_type for n in result.dag.all_nodes()]


def _unsupported(result) -> list:
    return [n for n in result.dag.all_nodes() if isinstance(n, UnsupportedNode)]


class TestNested:
    def test_a_macro_calling_a_macro_is_fully_expanded(self, tmp_path):
        _write(tmp_path / "Outer.yxmc", macro_calling("Inner.yxmc"))
        _write(tmp_path / "Inner.yxmc", formula_macro())
        wf = _write(tmp_path / "main.yxmd", workflow_calling("Outer.yxmc"))

        result = _expand(wf)

        assert result.expanded_calls == 2
        assert result.unresolved == []
        assert _unsupported(result) == []
        assert "Formula" in _types(result)
        order = [n.original_tool_type for n in result.dag.topological_order()]
        assert order[0] == "Input" and order[-1] == "Output"
        assert result.dag.validate() == []

    def test_nested_macro_is_found_next_to_the_macro_that_calls_it(self, tmp_path):
        # As in an extracted .yxzp: the inner macro sits beside the outer one,
        # not beside the workflow.
        _write(tmp_path / "lib" / "Outer.yxmc", macro_calling("Inner.yxmc"))
        _write(tmp_path / "lib" / "Inner.yxmc", formula_macro())
        wf = _write(tmp_path / "main.yxmd", workflow_calling("lib/Outer.yxmc"))

        result = _expand(wf)

        assert result.expanded_calls == 2
        assert _unsupported(result) == []

    def test_two_calls_to_the_same_nested_macro_get_distinct_ids(self, tmp_path):
        _write(tmp_path / "Outer.yxmc", macro_calling("Inner.yxmc"))
        _write(tmp_path / "Inner.yxmc", formula_macro())
        wf = _write(tmp_path / "main.yxmd", workflow_calling("Outer.yxmc", "Outer.yxmc"))

        result = _expand(wf)

        assert result.expanded_calls == 4
        assert _types(result).count("Formula") == 2
        ids = result.dag.all_node_ids()
        assert len(ids) == len(set(ids))
        assert result.dag.validate() == []

    def test_a_macro_that_calls_itself_is_reported_not_looped(self, tmp_path):
        _write(tmp_path / "Loop.yxmc", macro_calling("Loop.yxmc"))
        wf = _write(tmp_path / "main.yxmd", workflow_calling("Loop.yxmc"))

        result = _expand(wf)

        assert result.expanded_calls == 1
        assert len(result.unresolved) == 1
        assert "calls itself" in result.unresolved[0].reason
        assert len(_unsupported(result)) == 1

    def test_mutual_recursion_is_reported(self, tmp_path):
        _write(tmp_path / "A.yxmc", macro_calling("B.yxmc"))
        _write(tmp_path / "B.yxmc", macro_calling("A.yxmc"))
        wf = _write(tmp_path / "main.yxmd", workflow_calling("A.yxmc"))

        result = _expand(wf)

        assert result.expanded_calls == 2
        assert ["calls itself" in u.reason for u in result.unresolved] == [True]

    def test_nesting_stops_at_the_depth_limit(self, tmp_path):
        depth = MAX_NESTING_DEPTH + 2
        for level in range(depth):
            _write(tmp_path / f"M{level}.yxmc", macro_calling(f"M{level + 1}.yxmc"))
        _write(tmp_path / f"M{depth}.yxmc", formula_macro())
        wf = _write(tmp_path / "main.yxmd", workflow_calling("M0.yxmc"))

        result = _expand(wf)

        assert result.expanded_calls == MAX_NESTING_DEPTH
        assert len(result.unresolved) == 1
        assert "nested more than" in result.unresolved[0].reason


class TestLookup:
    def test_reference_case_differs_from_the_file_name(self, tmp_path):
        # Alteryx on Windows doesn't care about case; a Linux server would.
        _write(tmp_path / "Macros" / "StandardCleanse.yxmc", formula_macro())
        wf = _write(tmp_path / "main.yxmd", workflow_calling(r"macros\standardcleanse.YXMC"))

        result = _expand(wf)

        assert result.expanded_calls == 1
        assert _unsupported(result) == []

    def test_shared_macro_folder_is_searched(self, tmp_path):
        shared = tmp_path / "shared"
        _write(shared / "Cleanse.yxmc", formula_macro())
        wf = _write(tmp_path / "wf" / "main.yxmd", workflow_calling(r"C:\Alteryx\Macros\Cleanse.yxmc"))

        assert _expand(wf).expanded_calls == 0
        result = _expand(wf, search_paths=[shared])
        assert result.expanded_calls == 1
        assert _unsupported(result) == []

    def test_the_workflows_own_macro_wins_over_the_shared_one(self, tmp_path):
        shared = tmp_path / "shared"
        _write(shared / "Cleanse.yxmc", macro_calling("Missing.yxmc"))
        _write(tmp_path / "wf" / "Cleanse.yxmc", formula_macro())
        wf = _write(tmp_path / "wf" / "main.yxmd", workflow_calling("Cleanse.yxmc"))

        result = _expand(wf, search_paths=[shared])

        assert result.unresolved == []
        assert "Formula" in _types(result)

    def test_case_insensitive_lookup_still_refuses_to_escape(self, tmp_path):
        _write(tmp_path / "Secret.yxmc", formula_macro())
        root = tmp_path / "wf"
        root.mkdir()

        engine = MacroExpansionEngine()
        assert engine._resolve_path("../SECRET.yxmc", root) is None
        assert engine._resolve_path(r"..\secret.yxmc", root) is None


class TestMacroTypes:
    """Only standard macros are inlined: one pass can't reproduce a loop."""

    def test_a_batch_macro_is_left_unconverted_and_says_why(self, tmp_path):
        _write(tmp_path / "PerGroup.yxmc", formula_macro(runtime=BATCH))
        wf = _write(tmp_path / "main.yxmd", workflow_calling("PerGroup.yxmc"))

        result = _expand(wf)

        assert result.expanded_calls == 0
        (u,) = result.unresolved
        assert u.kind == "batch" and "batch macro" in u.reason
        (node,) = _unsupported(result)
        assert node.unsupported_reason.startswith("Macro PerGroup.yxmc wasn't expanded: it's a batch macro")

    def test_an_iterative_macro_is_left_unconverted(self, tmp_path):
        _write(tmp_path / "Loop.yxmc", formula_macro(runtime=ITERATIVE))
        wf = _write(tmp_path / "main.yxmd", workflow_calling("Loop.yxmc"))

        result = _expand(wf)

        assert result.expanded_calls == 0
        assert [u.kind for u in result.unresolved] == ["iterative"]

    def test_the_callers_dag_keeps_its_original_reason(self, tmp_path):
        # Expansion works on a clone that shares node objects with the input DAG.
        _write(tmp_path / "PerGroup.yxmc", formula_macro(runtime=BATCH))
        wf = _write(tmp_path / "main.yxmd", workflow_calling("PerGroup.yxmc"))
        parsed = WorkflowParser().parse(wf)
        base = ConversionPipeline(ConversionConfig())._build_dag(parsed)
        before = base.get_node(10).unsupported_reason

        MacroExpansionEngine().expand(parsed, base)

        assert base.get_node(10).unsupported_reason == before

    def test_a_macro_that_takes_settings_is_inlined_with_a_note(self, tmp_path):
        _write(tmp_path / "Param.yxmc", formula_macro(runtime=TAKES_SETTINGS))
        wf = _write(tmp_path / "main.yxmd", workflow_calling("Param.yxmc"))

        result = _expand(wf)

        assert result.expanded_calls == 1
        assert _unsupported(result) == []
        (note,) = result.notes
        assert "Param.yxmc (tool 10)" in note and "takes settings from the tool that calls it" in note

    def test_batch_warning_in_a_conversion(self, tmp_path):
        _write(tmp_path / "PerGroup.yxmc", formula_macro(runtime=BATCH))
        wf = _write(tmp_path / "main.yxmd", workflow_calling("PerGroup.yxmc"))

        result = ConversionPipeline(ConversionConfig(expand_macros=True)).convert_all_formats(wf)

        (warning,) = [w for w in result.warnings if "PerGroup.yxmc" in w]
        assert "batch macro" in warning and "rewrite by hand" in warning
        assert "supply the .yxmc" not in warning


class TestPipelineWarnings:
    def test_a_missing_macro_is_a_conversion_warning(self, tmp_path):
        wf = _write(tmp_path / "main.yxmd", workflow_calling("Nowhere.yxmc"))

        result = ConversionPipeline(ConversionConfig(expand_macros=True)).convert_all_formats(wf)

        notes = [w for w in result.warnings if "Nowhere.yxmc" in w]
        assert len(notes) == 1
        assert "tool 10" in notes[0] and "macro file not found" in notes[0]

    def test_config_search_paths_reach_the_engine(self, tmp_path):
        shared = tmp_path / "shared"
        _write(shared / "Cleanse.yxmc", formula_macro())
        wf = _write(tmp_path / "wf" / "main.yxmd", workflow_calling("Cleanse.yxmc"))

        config = ConversionConfig(expand_macros=True, macro_search_paths=(shared,))
        result = ConversionPipeline(config).convert_all_formats(wf)

        assert not any("Cleanse.yxmc" in w for w in result.warnings)
        assert not any(isinstance(n, UnsupportedNode) for n in result.dag.all_nodes())
