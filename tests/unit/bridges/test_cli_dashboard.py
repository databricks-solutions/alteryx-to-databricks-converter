"""Test `a2d convert --generate-dashboard`."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from a2d.cli import app

runner = CliRunner()

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "workflows"
CHART_WF = FIXTURES / "chart_workflow.yxmd"


class TestGenerateDashboard:
    def test_emits_lvdash_json(self, tmp_path):
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            ["convert", str(CHART_WF), "-f", "pyspark", "--generate-dashboard", "-o", str(out), "-q"],
        )
        assert result.exit_code == 0, result.output
        dash = out / "chart_workflow.lvdash.json"
        assert dash.exists()
        doc = json.loads(dash.read_text())
        assert doc["displayName"] == "chart_workflow"
        assert doc["pages"][0]["layout"]  # at least one widget

    def test_no_dashboard_without_flag(self, tmp_path):
        out = tmp_path / "out"
        runner.invoke(app, ["convert", str(CHART_WF), "-f", "pyspark", "-o", str(out), "-q"])
        assert not (out / "chart_workflow.lvdash.json").exists()
