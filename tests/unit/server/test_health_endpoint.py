"""Tests for /api/health and /api/stats endpoints."""

from __future__ import annotations


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_stats(client):
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "supported_tools" in data
    assert "total_tools" in data
    assert data["supported_tools"] > 0
    assert data["total_tools"] >= data["supported_tools"]
    assert data["expression_functions"] > 0
    assert data["output_formats"] == 4
    assert "version" in data
