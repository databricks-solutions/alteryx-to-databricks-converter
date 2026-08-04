"""Tests for the advisory /api/chat endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from server.services import chat as chat_service

from a2d.advisor.llm_client import ChatMessage, LLMRequestError


def _message_wf() -> bytes:
    path = Path(__file__).parent.parent.parent / "fixtures" / "workflows" / "message_passthrough.yxmd"
    return path.read_bytes()


class FakeClient:
    def __init__(self, reply: str = "Because the Message tool only logs.") -> None:
        self.reply = reply

    def chat(self, messages: list[ChatMessage], *, max_tokens: int = 1500) -> str:
        return self.reply


class FailingClient:
    def chat(self, messages, *, max_tokens: int = 1500) -> str:
        raise LLMRequestError("endpoint down")


@pytest.fixture(autouse=True)
def _clean_sessions():
    chat_service.clear_sessions()
    yield
    chat_service.clear_sessions()


@pytest.fixture()
def enabled(monkeypatch):
    """Pretend an FMAPI endpoint is configured, backed by a fake client."""
    client = FakeClient()
    monkeypatch.setattr(chat_service, "get_client", lambda *a, **k: client)
    return client


@pytest.fixture()
def disabled(monkeypatch):
    monkeypatch.setattr(chat_service, "get_client", lambda *a, **k: None)


class TestOptInGating:
    def test_status_reports_disabled(self, client, disabled):
        resp = client.get("/api/chat/status")
        assert resp.status_code == 200
        assert resp.json() == {"enabled": False}

    def test_status_reports_enabled(self, client, enabled):
        assert client.get("/api/chat/status").json() == {"enabled": True}

    def test_start_returns_422_when_not_configured(self, client, disabled):
        resp = client.post(
            "/api/chat",
            files={"file": ("wf.yxmd", _message_wf(), "application/xml")},
        )
        assert resp.status_code == 422
        assert "opt-in" in resp.json()["detail"]
        assert "A2D_FMAPI_ENDPOINT" in resp.json()["detail"]

    def test_message_returns_422_when_not_configured(self, client, disabled):
        resp = client.post("/api/chat/whatever/message", json={"message": "hi"})
        assert resp.status_code == 422


class TestSessionLifecycle:
    def _start(self, client) -> dict:
        resp = client.post(
            "/api/chat",
            files={"file": ("message_passthrough.yxmd", _message_wf(), "application/xml")},
            data={"output_format": "pyspark"},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_start_returns_grounded_session(self, client, enabled):
        data = self._start(client)
        assert data["session_id"]
        assert data["context"]["workflow_name"] == "message_passthrough"
        # The unsupported Message node is surfaced as a gap.
        assert data["context"]["summary"]["total_gaps"] >= 1
        # An opening summary is present without any model call.
        assert data["messages"][0]["role"] == "assistant"
        assert data["clarifying_questions"]

    def test_message_returns_reply_and_appends_history(self, client, enabled):
        session_id = self._start(client)["session_id"]
        resp = client.post(f"/api/chat/{session_id}/message", json={"message": "why?"})
        assert resp.status_code == 200
        assert resp.json()["reply"] == enabled.reply

        session = chat_service.get_session(session_id)
        assert [m["role"] for m in session.messages] == ["assistant", "user", "assistant"]

    def test_empty_message_rejected(self, client, enabled):
        session_id = self._start(client)["session_id"]
        resp = client.post(f"/api/chat/{session_id}/message", json={"message": "   "})
        assert resp.status_code == 422

    def test_unknown_session_404s(self, client, enabled):
        resp = client.post("/api/chat/nope/message", json={"message": "hi"})
        assert resp.status_code == 404

    def test_bad_output_format_422s(self, client, enabled):
        resp = client.post(
            "/api/chat",
            files={"file": ("wf.yxmd", _message_wf(), "application/xml")},
            data={"output_format": "cobol"},
        )
        assert resp.status_code == 422

    def test_non_yxmd_rejected(self, client, enabled):
        resp = client.post(
            "/api/chat",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 400


class TestReportDownload:
    def test_report_is_markdown_attachment(self, client, enabled):
        start = client.post(
            "/api/chat",
            files={"file": ("message_passthrough.yxmd", _message_wf(), "application/xml")},
        ).json()
        resp = client.post(f"/api/chat/{start['session_id']}/report", json={"Which catalog?": "main"})
        assert resp.status_code == 200
        assert "text/markdown" in resp.headers["content-type"]
        assert "attachment" in resp.headers["content-disposition"]
        assert "message_passthrough_suggestions.md" in resp.headers["content-disposition"]

        body = resp.text
        assert body.startswith("# Migration suggestions")
        assert "AI-generated advisory notes" in body
        assert "main" in body  # the supplied answer is recorded

    def test_report_422_when_not_configured(self, client, disabled):
        resp = client.post("/api/chat/any/report", json={})
        assert resp.status_code == 422


class TestModelFailures:
    def test_failing_endpoint_returns_502(self, client, monkeypatch):
        monkeypatch.setattr(chat_service, "get_client", lambda *a, **k: FailingClient())
        start = client.post(
            "/api/chat",
            files={"file": ("wf.yxmd", _message_wf(), "application/xml")},
        )
        # Session creation itself needs no model call, so it succeeds.
        assert start.status_code == 200, start.text
        session_id = start.json()["session_id"]

        resp = client.post(f"/api/chat/{session_id}/message", json={"message": "hi"})
        assert resp.status_code == 502
        assert "Model endpoint error" in resp.json()["detail"]


class TestNoCodeMutation:
    def test_chat_never_returns_editable_generated_code(self, client, enabled):
        """The API surface exposes facts and text — no writable code payload."""
        data = client.post(
            "/api/chat",
            files={"file": ("wf.yxmd", _message_wf(), "application/xml")},
        ).json()
        # Context carries descriptions, not the generated artifacts.
        assert set(data.keys()) == {"session_id", "context", "messages", "clarifying_questions"}
        assert "files" not in data["context"]
        assert "generated_code" not in data["context"]


class TestEvictedSessionGone:
    """An expired session must be distinguishable from a bad id."""

    def test_evicted_session_returns_410_not_404(self, client, enabled):
        start = client.post(
            "/api/chat",
            files={"file": ("wf.yxmd", _message_wf(), "application/xml")},
        ).json()
        session_id = start["session_id"]

        # Force expiry, then trigger the prune that a new session performs.
        chat_service.get_session(session_id).created_at = 0
        client.post("/api/chat", files={"file": ("wf.yxmd", _message_wf(), "application/xml")})

        resp = client.post(f"/api/chat/{session_id}/message", json={"message": "still there?"})

        assert resp.status_code == 410, resp.text
        assert "expired" in resp.json()["detail"].lower()

    def test_never_seen_session_still_returns_404(self, client, enabled):
        resp = client.post("/api/chat/deadbeef/message", json={"message": "hi"})
        assert resp.status_code == 404
