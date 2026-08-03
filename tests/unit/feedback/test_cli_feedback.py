"""Tests for `a2d assist --learn` and the `a2d feedback` command."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from a2d.cli import app

runner = CliRunner()

ASSIST_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "assist"
MESSAGE_WF = ASSIST_FIXTURES / "message_passthrough.yxmd"


def _orders(tmp_path: Path) -> Path:
    p = tmp_path / "orders.csv"
    p.write_text("order_id,amount\n1,100\n2,250\n")
    return p


class TestAssistLearn:
    def test_learn_records_verified(self, tmp_path, monkeypatch):
        store = tmp_path / "fb.json"
        monkeypatch.setenv("A2D_FEEDBACK_STORE", str(store))
        orders = _orders(tmp_path)
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
                "--learn",
                "-q",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Learned 1 verified conversion" in result.output
        assert store.exists()

    def test_feedback_lists_learned(self, tmp_path, monkeypatch):
        store = tmp_path / "fb.json"
        monkeypatch.setenv("A2D_FEEDBACK_STORE", str(store))
        orders = _orders(tmp_path)
        golden = tmp_path / "golden.csv"
        golden.write_text(orders.read_text())
        runner.invoke(
            app,
            ["assist", str(MESSAGE_WF), "-i", f"data/orders.csv={orders}", "-g", f"2={golden}", "--learn", "-q"],
        )

        result = runner.invoke(app, ["feedback", "-q"])
        assert result.exit_code == 0, result.output
        assert "Message" in result.output
        assert "1 mapping" in result.output

    def test_feedback_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("A2D_FEEDBACK_STORE", str(tmp_path / "empty.json"))
        result = runner.invoke(app, ["feedback", "-q"])
        assert result.exit_code == 0, result.output
        assert "No learned mappings yet" in result.output

    def test_feedback_clear(self, tmp_path, monkeypatch):
        store = tmp_path / "fb.json"
        monkeypatch.setenv("A2D_FEEDBACK_STORE", str(store))
        store.write_text('{"mappings": []}\n')
        result = runner.invoke(app, ["feedback", "--clear", "-q"])
        assert result.exit_code == 0, result.output
        assert "Cleared feedback store" in result.output
        assert not store.exists()
