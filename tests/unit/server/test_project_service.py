"""Migration Project service: pure logic, graceful degradation, and endpoint wiring.

Mirrors the history-service test philosophy — no database required. The DB CRUD
itself needs a live Postgres (exercised in deployment), so here we cover the
logic that must be right regardless of the database: rollup computation, stage
validation, the "no backend -> unavailable" degradation, and that the endpoints
answer 503 (not 500) when projects aren't configured.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from server.services import project as project_service

# ── pure logic (no DB) ────────────────────────────────────────────────────


def test_rollups_counts_stages_and_averages_coverage():
    workflows = [
        {"stage": "converted", "analysis": {"coverage_percentage": 100.0}},
        {"stage": "assessed", "analysis": {"coverage_percentage": 50.0}},
        {"stage": "uploaded", "analysis": None},
    ]
    r = project_service._rollups_from_workflows(workflows)
    assert r["total_workflows"] == 3
    assert r["stage_counts"]["converted"] == 1
    assert r["stage_counts"]["assessed"] == 1
    assert r["stage_counts"]["uploaded"] == 1
    assert r["mean_coverage_pct"] == 75.0


def test_rollups_omits_coverage_when_no_analysis():
    r = project_service._rollups_from_workflows([{"stage": "uploaded", "analysis": None}])
    assert "mean_coverage_pct" not in r  # not faked when there's nothing to average


def test_set_stage_rejects_unknown_stage():
    with pytest.raises(ValueError, match="unknown stage"):
        project_service.set_workflow_stage("p", "w", "nonsense")


def test_set_stage_rejects_unknown_artifact_key():
    with pytest.raises(ValueError, match="unknown artifact_key"):
        project_service.set_workflow_stage("p", "w", "converted", artifact_key="bogus", artifact={})


# ── graceful degradation (no backend) ─────────────────────────────────────


@pytest.fixture()
def _no_backend(monkeypatch):
    monkeypatch.setattr(project_service.history, "_get_pool", lambda: None)
    monkeypatch.setattr(project_service, "_initialized", False)


def test_unavailable_when_no_backend(_no_backend):
    assert project_service.is_available() is False
    assert project_service.create_project("x", [("a.yxmd", b"<x/>")]) is None
    assert project_service.get_project("id") is None
    assert project_service.list_projects() == ([], 0)
    assert project_service.get_workflow_file("p", "w") is None
    assert project_service.delete_project("id") is False
    # stage validation happens first, so a VALID stage with no backend returns False
    assert project_service.set_workflow_stage("p", "w", "converted") is False


def _pool_raising(exc: Exception):
    pool = MagicMock()
    pool.connection.side_effect = exc
    return pool


def test_db_error_degrades_not_raises(monkeypatch):
    monkeypatch.setattr(project_service, "_initialized", True)
    monkeypatch.setattr(
        project_service.history,
        "_get_pool",
        lambda: _pool_raising(project_service._DatabaseError("down")),
    )
    assert project_service.list_projects() == ([], 0)
    assert project_service.get_project("id") is None
    assert project_service.create_project("x", []) is None


# ── endpoint wiring (503 when unavailable) ─────────────────────────────────


def test_endpoints_503_when_projects_unavailable(client, monkeypatch):
    # No DB in the test env, so is_available() is False -> endpoints must 503,
    # never 500, so the client knows to fall back to in-session stores.
    monkeypatch.setattr(project_service, "is_available", lambda: False)
    assert client.get("/api/projects").status_code == 503
    assert client.get("/api/projects/abc").status_code == 503
    assert client.post("/api/projects/abc/workflows", files=[]).status_code in (503, 422)


def test_create_project_503_when_unavailable(client, simple_yxmd, monkeypatch):
    monkeypatch.setattr(project_service, "is_available", lambda: False)
    resp = client.post(
        "/api/projects",
        files=[("files", ("simple_filter.yxmd", simple_yxmd, "application/xml"))],
        data={"name": "Test migration"},
    )
    assert resp.status_code == 503
