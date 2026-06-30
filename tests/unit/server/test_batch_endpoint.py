"""Tests for /api/convert/batch endpoint."""

from __future__ import annotations

import time


def test_batch_creates_job(client, simple_yxmd):
    resp = client.post(
        "/api/convert/batch",
        files=[("files", ("simple_filter.yxmd", simple_yxmd, "application/xml"))],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert data["total_files"] == 1


def test_batch_status_not_found(client):
    resp = client.get("/api/convert/batch/nonexistent")
    assert resp.status_code == 404


def _poll_batch_status(client, job_id: str, timeout: float = 10.0, interval: float = 0.2):
    """Poll batch job status until completed/failed or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/api/convert/batch/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        if data["status"] in ("completed", "failed"):
            return data
        time.sleep(interval)
    return data


def test_batch_status_after_create(client, simple_yxmd):
    # Create job
    resp = client.post(
        "/api/convert/batch",
        files=[("files", ("simple_filter.yxmd", simple_yxmd, "application/xml"))],
    )
    job_id = resp.json()["job_id"]

    # Poll until done instead of sleeping
    data = _poll_batch_status(client, job_id)
    assert data["job_id"] == job_id
    assert data["status"] in ("pending", "running", "completed", "failed")


def test_batch_rejects_non_yxmd(client):
    resp = client.post(
        "/api/convert/batch",
        files=[("files", ("readme.txt", b"hello", "text/plain"))],
    )
    assert resp.status_code == 400
