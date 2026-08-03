"""Tests for the `a2d suggest` command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from a2d.advisor.llm_client import ENV_ENDPOINT
from a2d.cli import app

runner = CliRunner()

WORKFLOWS = Path(__file__).parent.parent.parent / "fixtures" / "workflows"
GAP_WF = WORKFLOWS / "message_passthrough.yxmd"


def _fake_fmapi_response(text: str = "Model suggestion here."):
    """A urlopen stand-in returning an OpenAI-compatible chat payload."""

    class _Response:
        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": text}}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None

    return _Response()


class TestOptInBehaviour:
    def test_without_endpoint_writes_report_and_succeeds(self, tmp_path, monkeypatch):
        """No endpoint is not an error — the deterministic gap list is still useful."""
        monkeypatch.delenv(ENV_ENDPOINT, raising=False)
        out = tmp_path / "s.md"
        result = runner.invoke(app, ["suggest", str(GAP_WF), "-o", str(out), "-q"])
        assert result.exit_code == 0, result.output
        assert out.exists()
        body = out.read_text()
        assert "Suggestions unavailable (AI is opt-in)" in body
        assert "**Suggested approach**" not in body

    def test_output_mentions_opt_in(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_ENDPOINT, raising=False)
        result = runner.invoke(app, ["suggest", str(GAP_WF), "-o", str(tmp_path / "s.md"), "-q"])
        assert "No FMAPI endpoint configured" in result.output

    def test_with_endpoint_includes_suggestions(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_ENDPOINT, raising=False)
        out = tmp_path / "s.md"
        with patch("urllib.request.urlopen", return_value=_fake_fmapi_response("Use a passthrough.")):
            result = runner.invoke(
                app,
                [
                    "suggest",
                    str(GAP_WF),
                    "-o",
                    str(out),
                    "--endpoint",
                    "https://example.invalid/invocations",
                    "--token",
                    "t",
                    "-q",
                ],
            )
        assert result.exit_code == 0, result.output
        body = out.read_text()
        assert "**Suggested approach**" in body
        assert "Use a passthrough." in body

    def test_env_var_enables_suggestions(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ENV_ENDPOINT, "https://example.invalid/invocations")
        out = tmp_path / "s.md"
        with patch("urllib.request.urlopen", return_value=_fake_fmapi_response("From env.")):
            result = runner.invoke(app, ["suggest", str(GAP_WF), "-o", str(out), "-q"])
        assert result.exit_code == 0, result.output
        assert "From env." in out.read_text()


class TestReportContent:
    def test_report_declares_itself_advisory(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_ENDPOINT, raising=False)
        out = tmp_path / "s.md"
        runner.invoke(app, ["suggest", str(GAP_WF), "-o", str(out), "-q"])
        body = out.read_text()
        assert "AI-generated advisory notes" in body
        assert "no generated file was modified" in body

    def test_default_output_path_next_to_workflow(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_ENDPOINT, raising=False)
        wf = tmp_path / "copy.yxmd"
        wf.write_bytes(GAP_WF.read_bytes())
        result = runner.invoke(app, ["suggest", str(wf), "-q"])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "copy_suggestions.md").exists()

    def test_does_not_write_any_code_file(self, tmp_path, monkeypatch):
        """`suggest` produces exactly one artifact: the Markdown document."""
        monkeypatch.delenv(ENV_ENDPOINT, raising=False)
        wf = tmp_path / "wf.yxmd"
        wf.write_bytes(GAP_WF.read_bytes())
        runner.invoke(app, ["suggest", str(wf), "-q"])
        produced = sorted(p.name for p in tmp_path.iterdir())
        assert produced == ["wf.yxmd", "wf_suggestions.md"]


class TestValidation:
    def test_missing_file_errors(self, tmp_path):
        result = runner.invoke(app, ["suggest", str(tmp_path / "nope.yxmd"), "-q"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_invalid_format_errors(self, tmp_path):
        result = runner.invoke(app, ["suggest", str(GAP_WF), "-f", "cobol", "-q"])
        assert result.exit_code == 1
        assert "Invalid --format" in result.output

    def test_invalid_cloud_errors(self, tmp_path):
        result = runner.invoke(app, ["suggest", str(GAP_WF), "--cloud", "moon", "-q"])
        assert result.exit_code == 1
        assert "Invalid --cloud" in result.output

    def test_sql_format_accepted(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_ENDPOINT, raising=False)
        out = tmp_path / "s.md"
        result = runner.invoke(app, ["suggest", str(GAP_WF), "-f", "sql", "-o", str(out), "-q"])
        assert result.exit_code == 0, result.output
        assert "Target format: `sql`" in out.read_text()
