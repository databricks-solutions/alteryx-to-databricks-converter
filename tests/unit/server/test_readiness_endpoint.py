"""Tests for the /api/readiness (migration-readiness questionnaire) endpoints."""

from __future__ import annotations


def test_readiness_questions(client):
    data = client.get("/api/readiness/questions").json()
    assert len(data["dimensions"]) == 4
    first = data["dimensions"][0]
    assert {"id", "label", "questions"} <= set(first)
    q0 = first["questions"][0]
    assert {"id", "prompt", "options"} <= set(q0)
    assert q0["options"], "questions must have options"
    assert "config_defaults" in data


def test_readiness_score_happy_path(client):
    resp = client.post(
        "/api/readiness/score",
        json={"answers": {"estate_size": "small", "spark_sql": "strong"}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["answered"] == 2
    assert 0 <= data["overall_score"] <= 100
    assert data["tier"]


def test_readiness_score_invalid_answer_is_422(client):
    resp = client.post("/api/readiness/score", json={"answers": {"estate_size": "nope"}})
    assert resp.status_code == 422


def test_readiness_score_bad_body_is_400(client):
    resp = client.post("/api/readiness/score", json={"answers": "not-an-object"})
    assert resp.status_code == 400


def test_readiness_malformed_tier_config_is_422_not_500(client):
    # A null min_score / non-numeric threshold must be a validation error (422),
    # not an unhandled TypeError surfaced as 500.
    r1 = client.post(
        "/api/readiness/score",
        json={"answers": {"estate_size": "small"}, "config": {"tiers": [{"name": "x", "min_score": None}]}},
    )
    assert r1.status_code == 422
    r2 = client.post(
        "/api/readiness/score",
        json={"answers": {"estate_size": "small"}, "config": {"tip_score_threshold": [1, 2]}},
    )
    assert r2.status_code == 422


def test_readiness_score_applies_config(client):
    body = {
        "answers": {"sponsorship": "strong", "spark_sql": "none"},
        "config": {"dimension_weights": {"governance": 5.0}},
    }
    weighted = client.post("/api/readiness/score", json=body).json()["overall_score"]
    base = client.post("/api/readiness/score", json={"answers": body["answers"]}).json()["overall_score"]
    assert weighted > base


def test_readiness_prefill(client, simple_yxmd):
    resp = client.post(
        "/api/readiness/prefill",
        files=[("files", ("simple_filter.yxmd", simple_yxmd, "application/xml"))],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["workflow_count"] == 1
    # estate questions get pre-answered from the file
    assert "estate_size" in data["answers"]


def test_readiness_prefill_rejects_non_alteryx(client):
    resp = client.post("/api/readiness/prefill", files=[("files", ("x.txt", b"hi", "text/plain"))])
    assert resp.status_code == 400
