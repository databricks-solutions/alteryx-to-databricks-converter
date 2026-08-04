"""Server resource limits: conversion deadline and batch-ZIP size cap.

Both guard against a single request monopolising the service — a workflow that
sends a generator into a pathological path would otherwise hold its worker thread
forever, and a full batch could allocate an unbounded in-memory archive.
"""

from __future__ import annotations

import time
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException
from server.services import batch as batch_service
from server.settings import settings
from server.utils.deadline import run_with_timeout


def _simple_wf() -> bytes:
    path = Path(__file__).parent.parent.parent / "fixtures" / "workflows" / "simple_filter.yxmd"
    return path.read_bytes()


class TestRunWithTimeout:
    @pytest.mark.asyncio
    async def test_returns_result_within_deadline(self):
        result = await run_with_timeout(lambda: 42, timeout=5.0)
        assert result == 42

    @pytest.mark.asyncio
    async def test_passes_through_args_and_kwargs(self):
        result = await run_with_timeout(lambda a, b=0: a + b, 1, b=2, timeout=5.0)
        assert result == 3

    @pytest.mark.asyncio
    async def test_raises_408_past_the_deadline(self):
        with pytest.raises(HTTPException) as exc:
            await run_with_timeout(lambda: time.sleep(2), timeout=0.05, label="Slow thing")
        assert exc.value.status_code == 408
        # The message must name the operation and be actionable.
        assert "Slow thing" in exc.value.detail
        assert "A2D_CONVERSION_TIMEOUT_SECONDS" in exc.value.detail

    @pytest.mark.asyncio
    async def test_worker_exception_propagates_unchanged(self):
        """A real error must not be disguised as a timeout."""
        with pytest.raises(ValueError, match="boom"):
            await run_with_timeout(lambda: (_ for _ in ()).throw(ValueError("boom")), timeout=5.0)

    @pytest.mark.asyncio
    async def test_defaults_to_settings_value(self, monkeypatch):
        monkeypatch.setattr(settings, "conversion_timeout_seconds", 0.05)
        with pytest.raises(HTTPException) as exc:
            await run_with_timeout(lambda: time.sleep(2))
        assert exc.value.status_code == 408


class TestConversionDeadlineWiring:
    def test_timeout_surfaces_as_408_not_500(self, client, monkeypatch):
        """A deadline must not be rewritten as an internal error by the broad handler."""
        monkeypatch.setattr(settings, "conversion_timeout_seconds", 0.01)

        def _slow(*a, **k):
            time.sleep(1)

        monkeypatch.setattr("server.routers.convert.convert_file", _slow)

        resp = client.post(
            "/api/convert",
            files={"file": ("simple_filter.yxmd", _simple_wf(), "application/xml")},
        )
        assert resp.status_code == 408, resp.text
        assert "took longer than" in resp.json()["detail"]

    def test_normal_conversion_unaffected(self, client):
        resp = client.post(
            "/api/convert",
            files={"file": ("simple_filter.yxmd", _simple_wf(), "application/xml")},
        )
        assert resp.status_code == 200


class TestBatchZipSizeCap:
    def _completed_job_with_payload(self, payload_bytes: int) -> str:
        """Register a completed batch job holding one large generated file."""
        job = batch_service.get_store().create(total=1)
        job.status = batch_service.JobStatus.COMPLETED
        job.file_results = [
            {
                "success": True,
                "workflow_name": "wf",
                "formats": {
                    "pyspark": {
                        "status": "success",
                        # Incompressible content, so the cap is reached predictably.
                        "files": [{"filename": "big.py", "content": _incompressible(payload_bytes)}],
                    }
                },
            }
        ]
        return job.job_id

    def test_oversized_zip_returns_413(self, client, monkeypatch):
        monkeypatch.setattr(settings, "max_zip_size_bytes", 50_000)
        job_id = self._completed_job_with_payload(400_000)

        resp = client.get(f"/api/convert/batch/{job_id}/download")

        assert resp.status_code == 413, resp.text
        assert "exceeds" in resp.json()["detail"]
        assert "A2D_MAX_ZIP_SIZE_BYTES" in resp.json()["detail"]

    def test_zip_under_the_cap_downloads_normally(self, client, monkeypatch):
        monkeypatch.setattr(settings, "max_zip_size_bytes", 10 * 1024 * 1024)
        job_id = self._completed_job_with_payload(1_000)

        resp = client.get(f"/api/convert/batch/{job_id}/download")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(BytesIO(resp.content)) as zf:
            assert zf.namelist() == ["wf/pyspark/big.py"]


def _incompressible(size: int) -> str:
    """Pseudo-random ASCII so ZIP_DEFLATED can't shrink it below the cap."""
    import random
    import string

    rnd = random.Random(0)
    return "".join(rnd.choice(string.ascii_letters + string.digits) for _ in range(size))
