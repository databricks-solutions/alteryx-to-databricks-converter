"""Tests for the cross-workflow portfolio analyzer."""

from __future__ import annotations

from pathlib import Path

from a2d.portfolio.analyzer import PortfolioAnalyzer

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "portfolio"


class TestPortfolioAnalyzerEndToEnd:
    def _report(self):
        files = sorted(FIXTURES.glob("*.yxmd"))
        return PortfolioAnalyzer().analyze(files)

    def test_all_workflows_analyzed(self):
        report = self._report()
        assert report.workflow_count == 3
        names = {a.workflow_name for a in report.analyses}
        assert names == {"wf_a_ingest", "wf_b_enrich", "wf_c_report"}

    def test_dependency_chain_detected(self):
        report = self._report()
        pairs = {(d.producer, d.consumer) for d in report.dependencies}
        assert ("wf_a_ingest", "wf_b_enrich") in pairs
        assert ("wf_b_enrich", "wf_c_report") in pairs

    def test_dependency_carries_artifact(self):
        report = self._report()
        first = next(d for d in report.dependencies if d.producer == "wf_a_ingest")
        assert first.artifact == "data/customers_clean.csv"

    def test_shared_macro_detected(self):
        report = self._report()
        assert len(report.shared_macros) == 1
        macro = report.shared_macros[0]
        assert macro.usage_count == 2
        assert macro.used_by == ["wf_a_ingest", "wf_b_enrich"]

    def test_duplicate_subflow_detected(self):
        report = self._report()
        assert len(report.duplicate_subflows) == 1
        dup = report.duplicate_subflows[0]
        assert dup.occurrence_count == 2
        assert dup.found_in == ["wf_a_ingest", "wf_b_enrich"]

    def test_no_isolated_workflows(self):
        report = self._report()
        assert report.isolated_workflows == []

    def test_wave_order_respects_dependencies(self):
        report = self._report()
        wave_of = {e.workflow_name: w.wave for w in report.plan.waves for e in w.workflows}
        assert wave_of["wf_a_ingest"] < wave_of["wf_b_enrich"]
        assert wave_of["wf_b_enrich"] < wave_of["wf_c_report"]


class TestPortfolioAnalyzerEdgeCases:
    def test_empty_list(self):
        report = PortfolioAnalyzer().analyze([])
        assert report.workflow_count == 0
        assert report.dependencies == []
        assert report.plan.waves == []

    def test_isolated_workflows_when_no_shared_assets(self):
        # The standalone fixtures under workflows/ share nothing.
        wf_dir = Path(__file__).parent.parent.parent / "fixtures" / "workflows"
        files = sorted(wf_dir.glob("*.yxmd"))
        report = PortfolioAnalyzer().analyze(files)
        assert report.dependencies == []
        assert len(report.isolated_workflows) == len(files)
