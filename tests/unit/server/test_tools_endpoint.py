"""Tests for /api/tools endpoint."""

from __future__ import annotations


def test_tools(client):
    resp = client.get("/api/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert "categories" in data
    assert "total_tools" in data
    assert "supported_tools" in data
    assert len(data["categories"]) > 0

    # Check structure of a tool entry
    for cat, tools in data["categories"].items():
        assert isinstance(tools, list)
        for tool in tools:
            assert "tool_type" in tool
            assert "category" in tool
            assert "supported" in tool
            assert tool["category"] == cat


def test_tools_has_known_categories(client):
    resp = client.get("/api/tools")
    data = resp.json()
    cats = set(data["categories"].keys())
    # Should have at least io, preparation, join
    assert "io" in cats
    assert "preparation" in cats
    assert "join" in cats
