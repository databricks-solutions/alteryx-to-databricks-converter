"""Test the `a2d advise` command."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from a2d.cli import app

runner = CliRunner()

WORKFLOWS = Path(__file__).parent.parent.parent / "fixtures" / "workflows"
JOIN_WF = WORKFLOWS / "join_and_summarize.yxmd"


class TestAdviseCommand:
    def test_prints_recommendation(self):
        result = runner.invoke(app, ["advise", str(JOIN_WF), "-q"])
        assert result.exit_code == 0, result.output
        assert "Recommended cluster" in result.output
        assert "advisory" in result.output.lower()

    def test_json_output(self, tmp_path):
        out = tmp_path / "advice.json"
        result = runner.invoke(app, ["advise", str(JOIN_WF), "--json", str(out), "-q"])
        assert result.exit_code == 0, result.output
        doc = json.loads(out.read_text())
        assert doc["cluster"]["tier"]
        assert "hints" in doc

    def test_cloud_option(self, tmp_path):
        out = tmp_path / "a.json"
        result = runner.invoke(app, ["advise", str(JOIN_WF), "--cloud", "gcp", "--json", str(out), "-q"])
        assert result.exit_code == 0, result.output
        assert json.loads(out.read_text())["cluster"]["node_type_id"] == "n1-highmem-4"

    def test_missing_file_errors(self, tmp_path):
        result = runner.invoke(app, ["advise", str(tmp_path / "nope.yxmd"), "-q"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_bad_cloud_errors(self):
        result = runner.invoke(app, ["advise", str(JOIN_WF), "--cloud", "moon", "-q"])
        assert result.exit_code == 1
