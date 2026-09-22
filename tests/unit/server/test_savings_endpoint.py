"""Tests for the /api/savings (migration savings / ROI) endpoints."""

from __future__ import annotations

import json


def test_savings_config_defaults(client):
    data = client.get("/api/savings/config-defaults").json()
    assert data["currency"] == "USD"
    assert data["designer_seats"] > 0
    assert "hour_anchors" in data
    # automation_factor defaults to null (derive from coverage)
    assert data["automation_factor"] is None


def test_savings_single_file(client, simple_yxmd):
    resp = client.post("/api/savings", files=[("files", ("simple_filter.yxmd", simple_yxmd, "application/xml"))])
    assert resp.status_code == 200
    data = resp.json()
    assert data["estate"]["workflow_count"] == 1
    assert {"headline", "lines", "assumptions", "disclaimer"} <= set(data)
    assert isinstance(data["headline"]["net_annual_savings"], int | float)


def test_savings_config_override_is_echoed(client, simple_yxmd):
    resp = client.post(
        "/api/savings",
        files=[("files", ("simple_filter.yxmd", simple_yxmd, "application/xml"))],
        data={"config": json.dumps({"designer_seats": 42, "developer_hourly_rate": 200})},
    )
    assert resp.status_code == 200
    assumptions = resp.json()["assumptions"]
    assert assumptions["designer_seats"] == 42
    assert assumptions["developer_hourly_rate"] == 200


def test_savings_bad_config_json(client, simple_yxmd):
    resp = client.post(
        "/api/savings",
        files=[("files", ("simple_filter.yxmd", simple_yxmd, "application/xml"))],
        data={"config": "{not valid"},
    )
    assert resp.status_code == 400


def test_savings_invalid_assumption_is_422(client, simple_yxmd):
    resp = client.post(
        "/api/savings",
        files=[("files", ("simple_filter.yxmd", simple_yxmd, "application/xml"))],
        data={"config": json.dumps({"developer_hourly_rate": -5})},
    )
    assert resp.status_code == 422


def test_savings_non_finite_assumption_is_422(client, simple_yxmd):
    # NaN/Infinity must be rejected at the boundary, not returned as a 200 whose
    # body contains bare `NaN` tokens (invalid JSON that breaks JSON.parse).
    files = [("files", ("simple_filter.yxmd", simple_yxmd, "application/xml"))]
    for bad in ("NaN", "Infinity", "1e309"):
        resp = client.post("/api/savings", files=files, data={"config": f'{{"developer_hourly_rate": {bad}}}'})
        assert resp.status_code == 422, f"{bad} should be 422, got {resp.status_code}"


def test_savings_rejects_non_alteryx(client):
    resp = client.post("/api/savings", files=[("files", ("readme.txt", b"hello", "text/plain"))])
    assert resp.status_code == 400


def test_savings_accepts_yxzp(client, simple_yxzp):
    resp = client.post("/api/savings", files=[("files", ("bundle.yxzp", simple_yxzp, "application/zip"))])
    assert resp.status_code == 200
    assert resp.json()["estate"]["workflow_count"] == 1
