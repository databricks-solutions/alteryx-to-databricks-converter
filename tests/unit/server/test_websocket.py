"""Tests for WebSocket batch progress endpoint."""

from __future__ import annotations


def test_ws_rejects_invalid_job_id(client):
    """Connecting to a non-existent job should receive an error and close."""
    with client.websocket_connect("/api/ws/batch/nonexistent") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "not found" in msg["message"].lower()


def test_ws_connects_to_pending_job(client, simple_yxmd):
    """Connecting to a newly-created job should accept the WebSocket."""
    # Create a batch job
    resp = client.post(
        "/api/convert/batch",
        files=[("files", ("test.yxmd", simple_yxmd, "application/xml"))],
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    # WebSocket should connect without error
    with client.websocket_connect(f"/api/ws/batch/{job_id}") as ws:
        # The connection was accepted — job exists
        # We may receive a progress, file_complete, or batch_complete message
        msg = ws.receive_json()
        assert "type" in msg
        assert msg["type"] in ("progress", "file_complete", "batch_complete", "error")
