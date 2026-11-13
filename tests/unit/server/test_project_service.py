"""Migration Project service: pure logic, graceful degradation, and endpoint wiring.

No database required. The DB CRUD
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
    monkeypatch.setattr(project_service.db, "get_pool", lambda: None)
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


def test_db_error_raises_store_unavailable(monkeypatch):
    # A configured database that fails is an outage (503), not "no projects" or
    # "deleted", so reads raise rather than returning empty values.
    monkeypatch.setattr(project_service, "_initialized", True)
    monkeypatch.setattr(
        project_service.db,
        "get_pool",
        lambda: _pool_raising(project_service._DatabaseError("down")),
    )
    with pytest.raises(project_service.StoreUnavailableError):
        project_service.list_projects()
    with pytest.raises(project_service.StoreUnavailableError):
        project_service.get_project("00000000-0000-0000-0000-000000000000")
    with pytest.raises(project_service.StoreUnavailableError):
        project_service.create_project("x", [])


def test_best_effort_bookkeeping_degrades_on_db_error(monkeypatch):
    monkeypatch.setattr(project_service, "_initialized", True)
    monkeypatch.setattr(
        project_service.db,
        "get_pool",
        lambda: _pool_raising(project_service._DatabaseError("down")),
    )
    assert project_service.record_conversion("p", "a.yxmd", {}) is False
    assert project_service.store_analysis("p", [{"file_name": "a.yxmd"}]) == 0
    assert project_service.advance_workflows_by_name("p", ["a.yxmd"], "assessed") == 0


def test_store_outage_is_a_503_with_its_own_message(client, monkeypatch):
    monkeypatch.setattr(project_service, "is_available", lambda: True)

    def down(*a, **k):
        raise project_service.StoreUnavailableError("Could not load projects; the database isn't responding.")

    monkeypatch.setattr(project_service, "list_projects", down)
    resp = client.get("/api/projects")
    assert resp.status_code == 503
    assert "isn't responding" in resp.json()["detail"]


def test_not_configured_and_unreachable_say_different_things(client, monkeypatch):
    monkeypatch.setattr(project_service, "is_available", lambda: False)
    monkeypatch.setattr(project_service, "is_configured", lambda: False)
    assert "doesn't have one configured" in client.get("/api/projects").json()["detail"]
    monkeypatch.setattr(project_service, "is_configured", lambda: True)
    assert "temporarily unavailable" in client.get("/api/projects").json()["detail"]


# ── endpoint wiring (503 when unavailable) ─────────────────────────────────


def test_endpoints_503_when_projects_unavailable(client, monkeypatch):
    # No DB in the test env, so is_available() is False -> endpoints must 503,
    # never 500, so the client knows to fall back to in-session stores.
    monkeypatch.setattr(project_service, "is_available", lambda: False)
    assert client.get("/api/projects").status_code == 503
    assert client.get("/api/projects/abc").status_code == 503
    files = [("files", ("a.yxmd", b"<AlteryxDocument/>", "application/xml"))]
    assert client.post("/api/projects/abc/workflows", files=files).status_code == 503


def test_create_project_503_when_unavailable(client, simple_yxmd, monkeypatch):
    monkeypatch.setattr(project_service, "is_available", lambda: False)
    resp = client.post(
        "/api/projects",
        files=[("files", ("simple_filter.yxmd", simple_yxmd, "application/xml"))],
        data={"name": "Test migration"},
    )
    assert resp.status_code == 503


# ── stage moves, workflow management, analysis mapping ─────────────────────


def test_forward_only_sql_compares_stage_positions():
    # The rule lives in SQL; make sure it compares positions in STAGES order
    # rather than overwriting unconditionally.
    sql = project_service._FORWARD_STAGE_SQL
    assert "array_position" in sql
    assert "ELSE stage END" in sql


def test_advance_by_name_rejects_unknown_stage():
    with pytest.raises(ValueError, match="unknown stage"):
        project_service.advance_workflows_by_name("p", ["a.yxmd"], "nonsense")


def test_rename_rejects_blank_name():
    with pytest.raises(ValueError, match="must not be empty"):
        project_service.rename_project("p", "   ")


def test_new_calls_degrade_without_backend(_no_backend):
    assert project_service.advance_workflows_by_name("p", ["a.yxmd"], "converted") == 0
    assert project_service.store_analysis("p", [{"file_name": "a.yxmd"}]) == 0
    assert project_service.record_conversion("p", "a.yxmd", {}) is False
    assert project_service.delete_workflow("p", "w") is False
    assert project_service.rename_project("p", "New name") is False


def test_new_endpoints_503_when_unavailable(client, monkeypatch):
    monkeypatch.setattr(project_service, "is_available", lambda: False)
    assert client.patch("/api/projects/abc", json={"name": "x"}).status_code == 503
    assert client.delete("/api/projects/abc/workflows/w").status_code == 503


def test_batch_from_a_project_without_a_database_is_503(client):
    # No database in the test env: a project-sourced batch must say so, not run empty.
    resp = client.post("/api/convert/batch", data={"project_id": "00000000-0000-0000-0000-000000000000"})
    assert resp.status_code == 503


def test_analysis_rows_carry_the_uploaded_name(simple_yxmd):
    from server.services.analysis import analyze_files

    result = analyze_files([("renamed_upload.yxmd", simple_yxmd)])
    assert result["workflows"][0]["source_file_name"] == "renamed_upload.yxmd"


def test_analysis_maps_a_package_back_to_its_upload_name(simple_yxzp):
    from server.services.analysis import analyze_files

    row = analyze_files([("my_package.yxzp", simple_yxzp)])["workflows"][0]
    assert row["source_file_name"] == "my_package.yxzp"
    assert row["file_name"] != row["source_file_name"]  # the package's primary workflow


def test_an_unreadable_workflow_is_skipped_not_fatal(simple_yxmd):
    from server.services.analysis import analyze_files

    result = analyze_files([("good.yxmd", simple_yxmd), ("bad.yxmd", b"<AlteryxDocument")])
    assert result["total_workflows"] == 1
    assert result["skipped_files"] == ["bad.yxmd"]


def test_content_hash_matches_what_the_database_computes():
    import base64
    import hashlib

    content = b"<AlteryxDocument/>"
    # Rows written before the column existed are backfilled with md5(source_b64).
    assert project_service.content_hash(content) == hashlib.md5(base64.b64encode(content)).hexdigest()


def test_malformed_artifact_key_is_422_not_500(client, monkeypatch):
    monkeypatch.setattr(project_service, "is_available", lambda: True)
    pid, wid = "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"
    resp = client.patch(f"/api/projects/{pid}/workflows/{wid}", json={"stage": "converted", "artifact_key": ["x"]})
    assert resp.status_code == 422


def test_project_download_handles_non_ascii_names(client, monkeypatch):
    monkeypatch.setattr(project_service, "is_available", lambda: True)
    monkeypatch.setattr(project_service, "get_workflow_file", lambda p, w: ('売上 "final".yxmd', b"<x/>"))
    pid, wid = "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"
    resp = client.get(f"/api/projects/{pid}/workflows/{wid}/file")
    assert resp.status_code == 200
    assert "filename*=UTF-8''" in resp.headers["content-disposition"]


def test_bad_project_id_is_404_without_a_query(client, monkeypatch):
    monkeypatch.setattr(project_service, "is_available", lambda: True)
    assert client.get("/api/projects/not-a-uuid").status_code == 404
