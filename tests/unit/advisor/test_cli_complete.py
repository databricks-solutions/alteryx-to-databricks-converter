"""Tests for the `a2d complete` command (AI-completed notebook copy)."""

from __future__ import annotations

import json
import shutil
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from a2d.advisor.completion import AI_BEGIN
from a2d.advisor.llm_client import ENV_ENDPOINT
from a2d.cli import app

runner = CliRunner()

GAP_WF = Path(__file__).parent.parent.parent / "fixtures" / "workflows" / "message_passthrough.yxmd"


def _reply(text: str = "df_1 = df_1.dropDuplicates()"):
    class _Response:
        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": text}}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None

    return _Response()


def _copy(tmp_path: Path) -> Path:
    wf = tmp_path / GAP_WF.name
    shutil.copy(GAP_WF, wf)
    return wf


def test_needs_an_endpoint(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_ENDPOINT, raising=False)
    result = runner.invoke(app, ["complete", str(_copy(tmp_path)), "-q"])
    assert result.exit_code == 1
    assert "needs a model endpoint" in result.output


def test_writes_a_separate_marked_copy(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_ENDPOINT, "https://example.invalid/serving-endpoints/x/invocations")
    wf = _copy(tmp_path)
    source_before = wf.read_bytes()
    with patch("a2d.advisor.llm_client.urllib.request.urlopen", return_value=_reply()):
        result = runner.invoke(app, ["complete", str(wf), "--token", "t", "-q"])
    assert result.exit_code == 0, result.output
    out = tmp_path / "message_passthrough.ai-completed.py"
    assert AI_BEGIN in out.read_text()
    assert wf.read_bytes() == source_before
    assert not (tmp_path / "message_passthrough.py").exists()  # the deterministic notebook isn't written or touched


def test_refuses_to_overwrite_the_source_or_its_notebook(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_ENDPOINT, "https://example.invalid/serving-endpoints/x/invocations")
    wf = _copy(tmp_path)
    for target in (wf, tmp_path / "message_passthrough.py"):
        result = runner.invoke(app, ["complete", str(wf), "--token", "t", "-o", str(target), "-q"])
        assert result.exit_code == 1
        assert "Refusing" in result.output
    assert wf.read_bytes() == GAP_WF.read_bytes()


def test_exits_1_when_every_step_failed(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_ENDPOINT, "https://example.invalid/serving-endpoints/x/invocations")
    with patch("a2d.advisor.llm_client.urllib.request.urlopen", side_effect=urllib.error.URLError("unreachable")):
        result = runner.invoke(app, ["complete", str(_copy(tmp_path)), "--token", "t", "-q"])
    assert result.exit_code == 1
    assert "Every step sent to the model failed" in result.output


def test_accepts_a_yxzp_package(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_ENDPOINT, "https://example.invalid/serving-endpoints/x/invocations")
    pkg = tmp_path / "bundle.yxzp"
    with zipfile.ZipFile(pkg, "w") as zf:
        zf.write(GAP_WF, GAP_WF.name)
    with patch("a2d.advisor.llm_client.urllib.request.urlopen", return_value=_reply()):
        result = runner.invoke(app, ["complete", str(pkg), "--token", "t", "-q"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "message_passthrough.ai-completed.py").exists()
