"""BatchAnalyzer macro-expansion behavior (Analyze / Profiler / Savings / Readiness).

Regression for the .yxzp report: a workflow that references a co-located .yxmc
was classified with the macro-call node as an unsupported "Unknown" because the
analysis path never ran macro expansion (only the conversion path did). With
``expand_macros=True`` the macro is inlined and coverage reflects its interior.
"""

from __future__ import annotations

from pathlib import Path

from a2d.analyzer.batch import BatchAnalyzer
from a2d.ir.nodes import UnsupportedNode

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "macro"
PARENT = FIXTURES / "parent_with_macro.yxmd"  # references macros/StandardCleanse.yxmc (co-located)


def _unsupported_count(analyzer: BatchAnalyzer, path: Path) -> int:
    parsed = analyzer._parser.parse(path)
    dag = analyzer.build_dag(parsed)
    return sum(1 for n in dag.all_nodes() if isinstance(n, UnsupportedNode))


def test_default_does_not_expand_macros():
    # Preserves existing CLI/behavior: the macro-call node stays unsupported.
    analyzer = BatchAnalyzer()
    assert _unsupported_count(analyzer, PARENT) >= 1


def test_expand_macros_inlines_the_macro():
    analyzer = BatchAnalyzer(expand_macros=True)
    assert _unsupported_count(analyzer, PARENT) == 0


def test_expand_macros_lifts_coverage():
    base = BatchAnalyzer().analyze_files([PARENT])[0]
    expanded = BatchAnalyzer(expand_macros=True).analyze_files([PARENT])[0]
    assert expanded.coverage.coverage_percentage > base.coverage.coverage_percentage
    assert expanded.coverage.coverage_percentage == 100.0


def test_expand_macros_is_safe_when_no_macro_present():
    # A workflow whose macro can't be resolved is left in place, never errors.
    missing = FIXTURES / "parent_missing_macro.yxmd"
    analyses = BatchAnalyzer(expand_macros=True).analyze_files([missing])
    assert len(analyses) == 1  # did not raise; unresolved macro left as-is
