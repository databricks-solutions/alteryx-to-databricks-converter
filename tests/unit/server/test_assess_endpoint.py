"""Tests for the /api/assess (migration profiler) endpoint."""

from __future__ import annotations


def _assert_profile_shape(data: dict) -> None:
    assert "totals" in data and "tool_difficulty" in data
    assert "difficulty_distribution" in data and "size_distribution" in data
    assert set(data["tool_difficulty"]["counts"]) == {"Low", "Medium", "High", "Very High"}
    assert isinstance(data["workflows"], list)


def test_assess_single_file(client, simple_yxmd):
    resp = client.post("/api/assess", files=[("files", ("simple_filter.yxmd", simple_yxmd, "application/xml"))])
    assert resp.status_code == 200
    data = resp.json()
    _assert_profile_shape(data)
    assert data["totals"]["workflows"] == 1
    assert data["total_hours"] is None  # hours off by default


def test_assess_hours_opt_in(client, simple_yxmd):
    resp = client.post(
        "/api/assess",
        files=[("files", ("simple_filter.yxmd", simple_yxmd, "application/xml"))],
        data={"hours": "true"},
    )
    assert resp.status_code == 200
    assert resp.json()["total_hours"] is not None


def test_assess_accepts_yxzp(client, simple_yxzp):
    resp = client.post("/api/assess", files=[("files", ("bundle.yxzp", simple_yxzp, "application/zip"))])
    assert resp.status_code == 200
    assert resp.json()["totals"]["workflows"] == 1


def test_assess_rejects_non_alteryx(client):
    resp = client.post("/api/assess", files=[("files", ("readme.txt", b"hello", "text/plain"))])
    assert resp.status_code == 400


def test_assess_no_files(client):
    resp = client.post("/api/assess")
    assert resp.status_code == 422  # FastAPI validation error


def test_config_defaults_endpoint(client):
    data = client.get("/api/assess/config-defaults").json()
    assert data["tiers"] == ["Low", "Medium", "High", "Very High"]
    assert data["category_tiers"]["spatial"] == "High"
    assert "hour_anchors" in data


def test_assess_config_override_shifts_tiers(client, simple_yxmd):
    import json

    files = [("files", ("simple_filter.yxmd", simple_yxmd, "application/xml"))]
    base = client.post("/api/assess", files=files).json()["tool_difficulty"]["counts"]
    over = client.post(
        "/api/assess",
        files=files,
        data={"config": json.dumps({"category_tiers": {"io": "High"}})},
    ).json()["tool_difficulty"]["counts"]
    # Moving io -> High must not leave the tier mix unchanged.
    assert over != base


def test_assess_invalid_tier_is_422(client, simple_yxmd):
    import json

    resp = client.post(
        "/api/assess",
        files=[("files", ("simple_filter.yxmd", simple_yxmd, "application/xml"))],
        data={"config": json.dumps({"category_tiers": {"io": "Nope"}})},
    )
    assert resp.status_code == 422


def test_assess_malformed_config_is_400(client, simple_yxmd):
    resp = client.post(
        "/api/assess",
        files=[("files", ("simple_filter.yxmd", simple_yxmd, "application/xml"))],
        data={"config": "{not valid json"},
    )
    assert resp.status_code == 400
