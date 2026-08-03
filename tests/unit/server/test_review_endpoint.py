"""Tests for the /api/review endpoint."""

from __future__ import annotations

from pathlib import Path


def _message_wf() -> bytes:
    path = Path(__file__).parent.parent.parent / "fixtures" / "workflows" / "message_passthrough.yxmd"
    return path.read_bytes()


def test_review_returns_session(client, simple_yxmd):
    resp = client.post(
        "/api/review",
        files={"file": ("simple_filter.yxmd", simple_yxmd, "application/xml")},
        data={"output_format": "pyspark"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["workflow_name"] == "simple_filter"
    assert data["output_format"] == "pyspark"
    assert data["summary"]["total"] > 0
    assert len(data["nodes"]) == data["summary"]["total"]
    for node in data["nodes"]:
        assert "generated_code" in node
        assert node["status"] in ("auto_accepted", "needs_review", "cannot_convert")
        assert node["decision"] == "pending"


def test_review_flags_unsupported_node(client):
    resp = client.post(
        "/api/review",
        files={"file": ("message.yxmd", _message_wf(), "application/xml")},
        data={"output_format": "pyspark"},
    )
    assert resp.status_code == 200
    data = resp.json()
    statuses = {n["node_id"]: n["status"] for n in data["nodes"]}
    assert "cannot_convert" in statuses.values()
    assert data["summary"]["complete"] is False


def test_review_defaults_to_pyspark(client, simple_yxmd):
    resp = client.post(
        "/api/review",
        files={"file": ("simple_filter.yxmd", simple_yxmd, "application/xml")},
    )
    assert resp.status_code == 200
    assert resp.json()["output_format"] == "pyspark"


def test_review_sql_format(client, simple_yxmd):
    resp = client.post(
        "/api/review",
        files={"file": ("simple_filter.yxmd", simple_yxmd, "application/xml")},
        data={"output_format": "sql"},
    )
    assert resp.status_code == 200
    assert resp.json()["output_format"] == "sql"


def test_review_rejects_bad_format(client, simple_yxmd):
    resp = client.post(
        "/api/review",
        files={"file": ("simple_filter.yxmd", simple_yxmd, "application/xml")},
        data={"output_format": "cobol"},
    )
    assert resp.status_code == 422


def test_review_rejects_non_yxmd(client):
    resp = client.post(
        "/api/review",
        files={"file": ("readme.txt", b"hello", "text/plain")},
    )
    assert resp.status_code in (400, 422)
