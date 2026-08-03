"""Tests for the `a2d portfolio` CLI command."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from a2d.cli import app

runner = CliRunner()

PORTFOLIO_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "portfolio"


class TestPortfolioCommand:
    def test_runs_and_writes_both_reports(self, tmp_path):
        out = tmp_path / "pf"
        result = runner.invoke(
            app,
            ["portfolio", str(PORTFOLIO_FIXTURES), "-o", str(out), "--format", "both", "-q"],
        )
        assert result.exit_code == 0, result.output
        assert (out / "portfolio_report.html").exists()
        assert (out / "portfolio_report.json").exists()

    def test_summary_printed(self, tmp_path):
        result = runner.invoke(
            app,
            ["portfolio", str(PORTFOLIO_FIXTURES), "-o", str(tmp_path / "pf"), "-q"],
        )
        assert result.exit_code == 0, result.output
        assert "Portfolio analysis" in result.output
        assert "cross-workflow dependencies" in result.output

    def test_json_content(self, tmp_path):
        out = tmp_path / "pf"
        runner.invoke(
            app,
            ["portfolio", str(PORTFOLIO_FIXTURES), "-o", str(out), "--format", "json", "-q"],
        )
        doc = json.loads((out / "portfolio_report.json").read_text())
        assert doc["summary"]["workflow_count"] == 3
        assert doc["summary"]["wave_count"] == 3

    def test_missing_path_errors(self, tmp_path):
        result = runner.invoke(app, ["portfolio", str(tmp_path / "nope"), "-q"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_empty_dir_errors(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(app, ["portfolio", str(empty), "-q"])
        assert result.exit_code == 1
        assert "No .yxmd files" in result.output

    def test_single_file_accepted(self, tmp_path):
        result = runner.invoke(
            app,
            [
                "portfolio",
                str(PORTFOLIO_FIXTURES / "wf_a_ingest.yxmd"),
                "-o",
                str(tmp_path / "pf"),
                "-q",
            ],
        )
        assert result.exit_code == 0, result.output
