"""Tests for /api/analyze endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_analyze_single_file(client, simple_yxmd):
    resp = client.post(
        "/api/analyze",
        files=[("files", ("simple_filter.yxmd", simple_yxmd, "application/xml"))],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_workflows"] == 1
    assert data["total_nodes"] > 0
    assert "avg_coverage" in data
    assert "avg_complexity" in data
    assert len(data["workflows"]) == 1
    wf = data["workflows"][0]
    assert wf["workflow_name"] == "simple_filter"
    assert "coverage_percentage" in wf
    assert "complexity_score" in wf
    assert wf["migration_priority"] in ("High", "Medium", "Low")


def test_analyze_multiple_files(client):
    fixtures = Path(__file__).parent.parent.parent / "fixtures" / "workflows"
    files = [("files", (p.name, p.read_bytes(), "application/xml")) for p in sorted(fixtures.glob("*.yxmd"))]
    if not files:
        pytest.skip("no .yxmd fixtures found in tests/fixtures/workflows")

    resp = client.post("/api/analyze", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_workflows"] == len(files)
    assert "tool_frequency" in data


def test_analyze_rejects_non_yxmd(client):
    resp = client.post(
        "/api/analyze",
        files=[("files", ("readme.txt", b"hello", "text/plain"))],
    )
    assert resp.status_code == 400
