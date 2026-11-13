"""Tests for the /api/ai endpoints (AI completion, gaps, notes)."""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

import pytest
from server.services import ai_completion
from server.services import project as project_service

from a2d.advisor.llm_client import ChatMessage

WF = Path(__file__).parent.parent.parent / "fixtures" / "workflows" / "message_passthrough.yxmd"
REPLY = "df_2 = df_1.limit(10)"


class FakeClient:
    def chat(self, messages: list[ChatMessage], *, max_tokens: int = 4000) -> str:
        return REPLY


@pytest.fixture()
def enabled(monkeypatch):
    monkeypatch.setattr(ai_completion, "get_client", lambda *a, **k: FakeClient())


@pytest.fixture()
def disabled(monkeypatch):
    monkeypatch.setattr(ai_completion, "get_client", lambda *a, **k: None)


def _upload(name: str = "message_passthrough.yxmd"):
    return {"file": (name, WF.read_bytes(), "application/xml")}


def test_status_reflects_configuration(client, enabled):
    assert client.get("/api/ai/status").json() == {"enabled": True}


def test_status_off_when_unconfigured(client, disabled):
    assert client.get("/api/ai/status").json() == {"enabled": False}


def test_gaps_work_without_ai_and_list_completable_steps(client, disabled):
    resp = client.post("/api/ai/gaps", files=_upload())
    assert resp.status_code == 200
    body = resp.json()
    assert any(g["tool_type"] == "Message" for g in body["gaps"])
    assert [s["node_id"] for s in body["completable"]] == [2]


def test_complete_and_notes_are_opt_in(client, disabled):
    for path in ("/api/ai/complete", "/api/ai/notes"):
        resp = client.post(path, files=_upload())
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


def test_complete_is_429_when_the_concurrency_limit_is_reached(client, enabled, monkeypatch):
    monkeypatch.setattr(ai_completion, "_completion_slots", threading.BoundedSemaphore(1))
    ai_completion._completion_slots.acquire()
    try:
        assert client.post("/api/ai/complete", files=_upload()).status_code == 429
    finally:
        ai_completion._completion_slots.release()


def test_notes_download_handles_non_ascii_names(client, enabled):
    resp = client.post("/api/ai/notes", files=_upload("売上.yxmd"))
    assert resp.status_code == 200
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "filename*=UTF-8''" in disposition
    assert "AI-generated advisory notes" in resp.text


def test_malformed_workflow_is_422_not_500(client, enabled):
    resp = client.post("/api/ai/gaps", files={"file": ("bad.yxmd", b"<AlteryxDocument", "application/xml")})
    assert resp.status_code == 422


def test_project_source_needs_both_ids(client, enabled):
    assert client.post("/api/ai/gaps", data={"project_id": str(uuid.uuid4())}).status_code == 422


def test_project_source_without_a_database_is_503(client, enabled):
    # No database in the test env: say so, rather than "unknown project".
    resp = client.post("/api/ai/gaps", data={"project_id": str(uuid.uuid4()), "workflow_id": str(uuid.uuid4())})
    assert resp.status_code == 503


def test_project_sourced_completion_reads_the_stored_workflow(client, enabled, monkeypatch):
    pid, wid = str(uuid.uuid4()), str(uuid.uuid4())
    seen = {}

    def fake_get(project_id, workflow_id):
        seen["ids"] = (project_id, workflow_id)
        return ("message_passthrough.yxmd", WF.read_bytes()), []

    monkeypatch.setattr(project_service, "is_available", lambda: True)
    monkeypatch.setattr(project_service, "get_workflow_with_macros", fake_get)
    resp = client.post("/api/ai/complete", data={"project_id": pid, "workflow_id": wid})
    assert resp.status_code == 200
    assert seen["ids"] == (pid, wid)
    assert resp.json()["summary"]["completed"] == 1


def test_nothing_to_work_on_is_422(client, enabled):
    assert client.post("/api/ai/gaps").status_code == 422


# ── /api/ai/suggest: one step, for Review ───────────────────────────────────


class RecordingClient:
    def __init__(self, reply: str = REPLY) -> None:
        self.reply, self.prompts = reply, []

    def chat(self, messages: list[ChatMessage], *, max_tokens: int = 4000) -> str:
        self.prompts.append(messages[-1].content)
        return self.reply


def test_suggest_returns_the_step_like_review_shows_it(client, monkeypatch):
    rec = RecordingClient()
    monkeypatch.setattr(ai_completion, "get_client", lambda *a, **k: rec)
    resp = client.post("/api/ai/suggest", files=_upload(), data={"node_id": "2", "hint": "keep 10 rows"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["node_id"] == 2 and body["status"] == "completed", body
    assert body["code"].startswith("# Step 2: Message\n# >>> AI-GENERATED")
    assert "df_2 = df_1.limit(10)" in body["code"]
    assert body["before"].startswith("# Step 2: Message")
    assert "The reviewer's note on this step" in rec.prompts[0] and "keep 10 rows" in rec.prompts[0]


def test_suggest_works_on_a_step_the_converter_finished(client, monkeypatch):
    """A reviewer can ask about any step, not only unfinished ones."""
    rec = RecordingClient("df_1 = spark.table('main.default.orders')")
    monkeypatch.setattr(ai_completion, "get_client", lambda *a, **k: rec)
    resp = client.post("/api/ai/suggest", files=_upload(), data={"node_id": "1"})
    assert resp.status_code == 200
    assert len(rec.prompts) == 1 and "Alteryx node id: 1" in rec.prompts[0]


def test_suggest_for_a_missing_macro_says_to_add_it(client, monkeypatch):
    rec = RecordingClient()
    monkeypatch.setattr(ai_completion, "get_client", lambda *a, **k: rec)
    path = Path(__file__).parent.parent.parent / "fixtures" / "macro" / "parent_missing_macro.yxmd"
    files = {"file": (path.name, path.read_bytes(), "application/xml")}
    body = client.post("/api/ai/suggest", files=files, data={"node_id": "2"}).json()
    assert body["status"] == "skipped"
    assert ".yxmc to the project" in body["reason"]
    assert rec.prompts == []  # no model call


def test_suggest_needs_a_step_with_code(client, enabled):
    resp = client.post("/api/ai/suggest", files=_upload(), data={"node_id": "999"})
    assert resp.status_code == 422
    assert "no PySpark code of its own" in resp.json()["detail"]


def test_suggest_is_opt_in_and_limits_the_note(client, disabled, monkeypatch):
    assert client.post("/api/ai/suggest", files=_upload(), data={"node_id": "2"}).status_code == 422
    monkeypatch.setattr(ai_completion, "get_client", lambda *a, **k: FakeClient())
    resp = client.post("/api/ai/suggest", files=_upload(), data={"node_id": "2", "hint": "x" * 2001})
    assert resp.status_code == 422
