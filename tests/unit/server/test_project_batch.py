"""Project-sourced batch conversion: selection, validation, and recording."""

from __future__ import annotations

import json

import pytest
from server.services import batch as batch_service
from server.services import project as project_service

PID = "00000000-0000-0000-0000-0000000000aa"


@pytest.fixture()
def project(monkeypatch, simple_yxmd):
    files = [("a.yxmd", simple_yxmd), ("b.yxmd", simple_yxmd)]
    monkeypatch.setattr(project_service, "is_available", lambda: True)
    monkeypatch.setattr(project_service, "get_project_files", lambda pid: files if pid == PID else None)
    started = {}

    async def fake_create(file_data, **kwargs):
        started["names"] = [name for name, _ in file_data]
        started["project_id"] = kwargs.get("project_id")
        return "job-1"

    monkeypatch.setattr(batch_service, "create_batch_job", fake_create)
    return started


def test_selection_narrows_the_run(client, project):
    resp = client.post("/api/convert/batch", data={"project_id": PID, "workflow_names": json.dumps(["b.yxmd"])})
    assert resp.status_code == 200
    assert resp.json()["total_files"] == 1
    assert project == {"names": ["b.yxmd"], "project_id": PID}


def test_whole_project_runs_without_a_selection(client, project):
    assert client.post("/api/convert/batch", data={"project_id": PID}).json()["total_files"] == 2


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        ({"project_id": PID, "workflow_names": json.dumps(["b.yxmd", "nope.yxmd"])}, "Not in this project: nope.yxmd"),
        ({"project_id": PID, "workflow_names": "[]"}, "Select at least one"),
        ({"project_id": PID, "workflow_names": "not json"}, "JSON list"),
        ({"workflow_names": json.dumps(["a.yxmd"])}, "only applies with a project_id"),
    ],
)
def test_bad_selections_are_rejected(client, project, data, fragment):
    resp = client.post("/api/convert/batch", data=data)
    assert resp.status_code == 422
    assert fragment in resp.json()["detail"]


def test_uploads_and_a_project_together_are_rejected(client, project, simple_yxmd):
    resp = client.post(
        "/api/convert/batch",
        data={"project_id": PID},
        files=[("files", ("c.yxmd", simple_yxmd, "application/xml"))],
    )
    assert resp.status_code == 422


def test_project_runs_have_the_upload_limits(client, project, monkeypatch):
    from server.settings import settings

    monkeypatch.setattr(settings, "max_batch_files", 1)
    resp = client.post("/api/convert/batch", data={"project_id": PID})
    assert resp.status_code == 400
    assert "at most 1" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_each_success_is_recorded_against_the_converted_bytes(monkeypatch, simple_yxmd):
    recorded = []
    monkeypatch.setattr(
        project_service,
        "record_conversion",
        lambda pid, name, summary, expected_hash=None: recorded.append((pid, name, expected_hash)),
    )
    job = batch_service._store.create(total=1)
    await batch_service._run_batch(job, [("a.yxmd", simple_yxmd)], project_id=PID)
    assert job.status == batch_service.JobStatus.COMPLETED
    assert recorded == [(PID, "a.yxmd", project_service.content_hash(simple_yxmd))]
    assert job.file_results[0]["source_file_name"] == "a.yxmd"


@pytest.mark.asyncio
async def test_nothing_is_recorded_without_a_project(monkeypatch, simple_yxmd):
    recorded = []
    monkeypatch.setattr(project_service, "record_conversion", lambda *a, **k: recorded.append(a))
    job = batch_service._store.create(total=1)
    await batch_service._run_batch(job, [("a.yxmd", simple_yxmd)])
    assert recorded == []


def test_running_jobs_are_not_evicted_while_making_progress(monkeypatch):
    from server.settings import settings

    store = batch_service.JobStore()
    job = store.create(total=10)
    job.status = batch_service.JobStatus.RUNNING
    job.created_at -= settings.job_ttl_seconds * 2  # old, but still active
    assert store.evict_expired() == 0
    job.last_activity -= settings.job_ttl_seconds * 2  # stuck
    assert store.evict_expired() == 1
