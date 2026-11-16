"""Usage tracking without a database: which requests count, who's asking, who may look."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from server.main import _tracked, app
from server.services import usage
from server.settings import settings


@pytest.mark.parametrize(
    ("method", "path", "action", "project"),
    [
        ("POST", "/api/convert", "convert", None),
        ("POST", "/api/convert/batch", "convert_batch", None),
        ("POST", "/api/ai/complete", "ai_complete", None),
        ("POST", "/api/projects", "project_create", None),
        ("POST", "/api/projects/abc/workflows", "workflows_add", "abc"),
        ("DELETE", "/api/projects/abc", "project_delete", "abc"),
        ("GET", "/", "open_app", None),
        ("GET", "/p/abc/convert", "open_app", None),
        ("GET", "/assets/index.js", None, None),
        ("GET", "/api/health", None, None),
        ("GET", "/api/convert/batch/123", None, None),  # polling a batch isn't a new conversion
        ("PATCH", "/api/projects/abc/workflows/w1", None, None),  # autosave isn't usage
    ],
)
def test_which_requests_are_recorded(method, path, action, project):
    assert _tracked(method, path) == (action, project)


def test_a_conversion_is_recorded_with_its_user_and_details(monkeypatch):
    from pathlib import Path

    seen = []
    monkeypatch.setattr(usage, "record", lambda action, **kw: seen.append((action, kw)))
    wf = Path(__file__).parents[2] / "fixtures" / "workflows" / "simple_filter.yxmd"
    resp = TestClient(app).post(
        "/api/convert",
        files={"file": (wf.name, wf.read_bytes(), "application/xml")},
        headers={"X-Forwarded-Email": "Someone@Example.com"},
    )
    assert resp.status_code == 200
    (_action, kw), *_ = [e for e in seen if e[0] == "convert"]
    assert kw["user"] == "someone@example.com" and kw["status"] == 200
    assert kw["details"]["workflow"] == "simple_filter.yxmd" and kw["details"]["coverage"] == resp.json()["coverage"]


def test_tracking_off_records_nothing(monkeypatch):
    seen = []
    monkeypatch.setattr(usage, "record", lambda action, **kw: seen.append(action))
    monkeypatch.setattr(settings, "usage_tracking", False)
    TestClient(app).get("/")
    assert seen == []


def test_nobody_sees_usage_until_admins_are_set(monkeypatch):
    monkeypatch.setattr(settings, "usage_admins", "")
    client = TestClient(app)
    assert client.get("/api/usage", headers={"X-Forwarded-Email": "a@example.com"}).status_code == 403
    body = client.get("/api/usage/access", headers={"X-Forwarded-Email": "a@example.com"}).json()
    assert body["allowed"] is False and body["admins_configured"] is False


def test_an_admin_without_a_database_gets_an_empty_summary(monkeypatch):
    monkeypatch.setattr(settings, "usage_admins", "A@example.com, b@example.com")
    resp = TestClient(app).get("/api/usage", headers={"X-Forwarded-Email": "a@example.com"})
    assert resp.status_code == 200 and resp.json()["database"] is False


def test_recording_never_raises_without_a_database():
    usage.record("convert", user="a@example.com", status=200)
