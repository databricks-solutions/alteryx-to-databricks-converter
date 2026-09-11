"""Tests for the WebSocket batch progress endpoint.

These assert the actual protocol (ordered progress/file_complete/batch_complete
with real payloads and a genuine terminal message), not merely that *some*
message of *some* type arrives — a job that errored immediately or never
completed used to satisfy the old assertion.
"""

from __future__ import annotations

# Non-terminal message types that may precede completion.
_INTERIM = {"progress", "file_complete"}


def _drain(ws, max_msgs: int = 100) -> list[dict]:
    """Collect messages until a terminal (batch_complete/error) one, or a cap."""
    msgs: list[dict] = []
    for _ in range(max_msgs):
        msg = ws.receive_json()
        msgs.append(msg)
        if msg["type"] in ("batch_complete", "error"):
            break
    return msgs


def _seed_completed_job() -> str:
    """Register a COMPLETED batch job directly in the store.

    The live conversion task only advances inside a long-lived await, which makes
    end-to-end completion fragile under the synchronous TestClient. Seeding a
    terminal job lets us assert the WebSocket's deterministic replay protocol
    (file_complete(s) then batch_complete, with real payloads) reliably.
    """
    from server.services.batch import JobStatus, _store

    job = _store.create(total=1)
    job.status = JobStatus.COMPLETED
    job.progress = 1
    job.file_results = [
        {"file_name": "test.yxmd", "workflow_name": "test", "success": True, "node_count": 3, "formats": {}}
    ]
    job.batch_metrics = {
        "total_files": 1,
        "successful_files": 1,
        "failed_files": 0,
        "partial_files": 0,
    }
    job.errors_by_kind = {}
    return job.job_id


def test_ws_rejects_invalid_job_id(client):
    """Connecting to a non-existent job receives an error and closes."""
    with client.websocket_connect("/api/ws/batch/nonexistent") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "not found" in msg["message"].lower()


def test_ws_protocol_ends_in_batch_complete_with_payload(client):
    """A completed job replays a well-formed sequence: interim file_complete(s)
    then a genuine terminal batch_complete carrying results and metrics, no error."""
    job_id = _seed_completed_job()

    with client.websocket_connect(f"/api/ws/batch/{job_id}") as ws:
        msgs = _drain(ws)

    types = [m["type"] for m in msgs]
    # Must terminate, and terminate as complete (never error).
    assert types[-1] == "batch_complete", f"did not complete cleanly: {types}"
    assert "error" not in types
    # Every non-terminal message is a known interim type, and the finished file
    # is replayed as file_complete (not just a bare progress ping).
    assert all(t in _INTERIM for t in types[:-1]), types
    assert "file_complete" in types

    file_msg = next(m for m in msgs if m["type"] == "file_complete")
    assert file_msg["workflow_name"] == "test"
    assert file_msg["success"] is True

    terminal = msgs[-1]
    assert len(terminal["file_results"]) == 1
    metrics = terminal["batch_metrics"]
    assert metrics["total_files"] == 1
    assert metrics["successful_files"] + metrics["failed_files"] + metrics["partial_files"] == 1
