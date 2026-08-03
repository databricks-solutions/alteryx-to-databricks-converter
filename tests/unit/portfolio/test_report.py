"""Tests for portfolio report rendering (HTML/JSON)."""

from __future__ import annotations

import json
from pathlib import Path

from a2d.portfolio.analyzer import PortfolioAnalyzer
from a2d.portfolio.report import _esc, generate_html, generate_json

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "portfolio"


def _report():
    return PortfolioAnalyzer().analyze(sorted(FIXTURES.glob("*.yxmd")))


class TestJson:
    def test_json_is_valid_and_structured(self, tmp_path):
        out = tmp_path / "portfolio.json"
        generate_json(_report(), out)
        doc = json.loads(out.read_text())
        assert doc["summary"]["workflow_count"] == 3
        assert doc["summary"]["dependency_count"] == 2
        assert len(doc["migration_plan"]["waves"]) == 3

    def test_json_includes_depends_on(self, tmp_path):
        out = tmp_path / "portfolio.json"
        generate_json(_report(), out)
        doc = json.loads(out.read_text())
        entries = {e["workflow_name"]: e for w in doc["migration_plan"]["waves"] for e in w["workflows"]}
        assert entries["wf_b_enrich"]["depends_on"] == ["wf_a_ingest"]


class TestHtml:
    def test_html_written_and_contains_sections(self, tmp_path):
        out = tmp_path / "portfolio.html"
        generate_html(_report(), out)
        html = out.read_text()
        assert "<!DOCTYPE html>" in html
        assert "Migration-Wave Plan" in html
        assert "Cross-Workflow Data Dependencies" in html
        assert "wf_a_ingest" in html

    def test_esc_escapes_html(self):
        assert _esc('<a & "b">') == "&lt;a &amp; &quot;b&quot;&gt;"
