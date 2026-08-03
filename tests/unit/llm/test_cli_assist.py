"""Tests for the `a2d assist` CLI command."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from a2d.cli import app

runner = CliRunner()

ASSIST_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "assist"
MESSAGE_WF = ASSIST_FIXTURES / "message_passthrough.yxmd"


def _write_orders(tmp_path: Path) -> Path:
    p = tmp_path / "orders.csv"
    p.write_text("order_id,amount\n1,100\n2,250\n3,75\n")
    return p


class TestAssistCommand:
    def test_runs_without_sample_data(self):
        result = runner.invoke(app, ["assist", str(MESSAGE_WF), "-q"])
        assert result.exit_code == 0, result.output
        assert "unsupported node" in result.output
        assert "unverified" in result.output

    def test_verifies_with_sample_and_golden(self, tmp_path):
        orders = _write_orders(tmp_path)
        golden = tmp_path / "golden.csv"
        golden.write_text(orders.read_text())
        result = runner.invoke(
            app,
            [
                "assist",
                str(MESSAGE_WF),
                "-i",
                f"data/orders.csv={orders}",
                "-g",
                f"2={golden}",
                "-q",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "verified" in result.output
        assert "safe to adopt" in result.output

    def test_json_output(self, tmp_path):
        orders = _write_orders(tmp_path)
        golden = tmp_path / "golden.csv"
        golden.write_text(orders.read_text())
        out = tmp_path / "assist.json"
        result = runner.invoke(
            app,
            [
                "assist",
                str(MESSAGE_WF),
                "-i",
                f"data/orders.csv={orders}",
                "-g",
                f"2={golden}",
                "--json",
                str(out),
                "-q",
            ],
        )
        assert result.exit_code == 0, result.output
        doc = json.loads(out.read_text())
        assert doc["unsupported_total"] == 1
        assert doc["verified"] == 1
        assert doc["nodes"][0]["status"] == "verified"

    def test_missing_file_errors(self, tmp_path):
        result = runner.invoke(app, ["assist", str(tmp_path / "nope.yxmd"), "-q"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_invalid_golden_spec_errors(self, tmp_path):
        orders = _write_orders(tmp_path)
        result = runner.invoke(
            app,
            ["assist", str(MESSAGE_WF), "-i", f"data/orders.csv={orders}", "-g", "notanumber=x.csv", "-q"],
        )
        assert result.exit_code == 1
