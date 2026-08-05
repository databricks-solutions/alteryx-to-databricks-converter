"""Batch cancellation must actually stop server-side work.

The UI's Cancel button previously only closed its WebSocket and reported
"Batch conversion cancelled" while the server kept converting every remaining
file. The user was told something untrue and the compute was wasted, so these
tests pin the real behaviour.
"""

from __future__ import annotations

from server.services import batch as batch_service


def _running_job():
    job = batch_service.get_store().create(total=3)
    job.status = batch_service.JobStatus.RUNNING
    return job


class TestCancelEndpoint:
    def test_cancelling_a_running_job_marks_it_cancelled(self, client):
        job = _running_job()

        resp = client.post(f"/api/convert/batch/{job.job_id}/cancel")

        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "cancelled"
        assert batch_service.get_job(job.job_id).status == batch_service.JobStatus.CANCELLED

    def test_unknown_job_is_404(self, client):
        assert client.post("/api/convert/batch/does-not-exist/cancel").status_code == 404

    def test_completed_job_cannot_be_cancelled(self, client):
        job = batch_service.get_store().create(total=1)
        job.status = batch_service.JobStatus.COMPLETED

        resp = client.post(f"/api/convert/batch/{job.job_id}/cancel")

        assert resp.status_code == 409
        assert "completed" in resp.json()["detail"]

    def test_cancelling_twice_is_rejected_the_second_time(self, client):
        job = _running_job()

        assert client.post(f"/api/convert/batch/{job.job_id}/cancel").status_code == 200
        assert client.post(f"/api/convert/batch/{job.job_id}/cancel").status_code == 409

    def test_status_endpoint_reports_the_cancellation(self, client):
        """The client polls status, so it must see the new state."""
        job = _running_job()
        client.post(f"/api/convert/batch/{job.job_id}/cancel")

        resp = client.get(f"/api/convert/batch/{job.job_id}")

        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"


class TestCancelService:
    def test_returns_false_for_unknown_job(self):
        assert batch_service.cancel_job("nope") is False

    def test_cancels_the_underlying_task(self):
        """Without cancelling the task, conversion would continue regardless."""
        import asyncio

        async def _check():
            async def _never():
                await asyncio.sleep(3600)

            job = _running_job()
            job.task = asyncio.create_task(_never())
            assert batch_service.cancel_job(job.job_id) is True
            await asyncio.sleep(0)  # let cancellation propagate
            assert job.task.cancelled() or job.task.done()

        asyncio.run(_check())
