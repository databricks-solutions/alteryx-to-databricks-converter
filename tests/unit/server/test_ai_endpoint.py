"""Tests for the /api/ai endpoints (AI completion, gaps, notes)."""

from __future__ import annotations

from pathlib import Path

import pytest
from server.services import chat as chat_service

from a2d.advisor.llm_client import ChatMessage

WF = Path(__file__).parent.parent.parent / "fixtures" / "workflows" / "message_passthrough.yxmd"
REPLY = "# Step 2: Message\ndf_1 = df_1.limit(10)"


class FakeClient:
    def chat(self, messages: list[ChatMessage], *, max_tokens: int = 4000) -> str:
        return REPLY


@pytest.fixture()
def enabled(monkeypatch):
    monkeypatch.setattr(chat_service, "get_client", lambda *a, **k: FakeClient())


@pytest.fixture()
def disabled(monkeypatch):
    monkeypatch.setattr(chat_service, "get_client", lambda *a, **k: None)


def _upload():
    return {"file": ("message_passthrough.yxmd", WF.read_bytes(), "application/xml")}


def test_status_reflects_configuration(client, enabled):
    assert client.get("/api/ai/status").json() == {"enabled": True}


def test_gaps_work_without_ai(client, disabled):
    resp = client.post("/api/ai/gaps", files=_upload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["total_gaps"] >= 1
    assert any(g["tool_type"] == "Message" for g in body["gaps"])


def test_complete_is_opt_in(client, disabled):
    resp = client.post("/api/ai/complete", files=_upload())
    assert resp.status_code == 422
    assert "A2D_FMAPI_ENDPOINT" in resp.json()["detail"]


def test_complete_returns_marked_copy(client, enabled):
    resp = client.post("/api/ai/complete", files=_upload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == "message_passthrough.ai-completed.py"
    assert body["deterministic_filename"] == "message_passthrough.py"
    assert body["summary"]["completed"] == 1
    assert "AI-GENERATED" in body["content"]


def test_notes_download_is_markdown(client, enabled):
    resp = client.post("/api/ai/notes", files=_upload())
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    assert "AI-generated advisory notes" in resp.text


def test_project_source_needs_both_ids(client, enabled):
    resp = client.post("/api/ai/gaps", data={"project_id": "p"})
    assert resp.status_code == 422


def test_unknown_project_workflow_is_404(client, enabled):
    # No database in the test env, so no project can be found.
    resp = client.post("/api/ai/gaps", data={"project_id": "p", "workflow_id": "w"})
    assert resp.status_code == 404


def test_nothing_to_work_on_is_422(client, enabled):
    assert client.post("/api/ai/gaps").status_code == 422
