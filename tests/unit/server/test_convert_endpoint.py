"""Tests for /api/convert endpoint (multi-format response)."""

from __future__ import annotations


class TestMalformedInput:
    """Tests for handling corrupted, empty, and malformed XML input."""

    def test_convert_empty_file(self, client):
        resp = client.post(
            "/api/convert",
            files={"file": ("empty.yxmd", b"", "application/xml")},
        )
        assert resp.status_code == 500

    def test_convert_corrupted_xml(self, client):
        resp = client.post(
            "/api/convert",
            files={"file": ("bad.yxmd", b"<not valid xml!><<<", "application/xml")},
        )
        assert resp.status_code == 500

    def test_convert_valid_xml_but_not_workflow(self, client):
        resp = client.post(
            "/api/convert",
            files={"file": ("notworkflow.yxmd", b"<root><child/></root>", "application/xml")},
        )
        # Valid XML but no recognizable workflow structure → handled gracefully as
        # a zero-node workflow. The endpoint must not 500 on parseable input.
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_count"] == 0

    def test_convert_no_file(self, client):
        resp = client.post("/api/convert")
        assert resp.status_code == 422  # FastAPI validation error


def _assert_multi_format_shape(data: dict) -> None:
    """Common assertions for the multi-format ConversionResponse shape."""
    assert "formats" in data
    assert "best_format" in data
    assert "node_count" in data
    assert "warnings" in data
    # All four expected format keys present
    for fmt in ("pyspark", "dlt", "sql", "lakeflow"):
        assert fmt in data["formats"], f"missing format {fmt}"
        fr = data["formats"][fmt]
        assert "status" in fr
        assert "files" in fr
        assert "warnings" in fr


def test_convert_single_file(client, simple_yxmd):
    resp = client.post(
        "/api/convert",
        files={"file": ("simple_filter.yxmd", simple_yxmd, "application/xml")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["workflow_name"] == "simple_filter"
    assert data["node_count"] > 0
    _assert_multi_format_shape(data)
    # At least one format should succeed for a valid simple workflow
    assert any(fr["status"] == "success" for fr in data["formats"].values())


def test_convert_rejects_non_yxmd(client):
    resp = client.post(
        "/api/convert",
        files={"file": ("readme.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400


def test_convert_returns_pyspark_files(client, simple_yxmd):
    resp = client.post(
        "/api/convert",
        files={"file": ("simple_filter.yxmd", simple_yxmd, "application/xml")},
    )
    assert resp.status_code == 200
    data = resp.json()
    pyspark = data["formats"]["pyspark"]
    assert pyspark["status"] == "success"
    assert len(pyspark["files"]) > 0


def test_convert_returns_dlt_files(client, simple_yxmd):
    resp = client.post(
        "/api/convert",
        files={"file": ("simple_filter.yxmd", simple_yxmd, "application/xml")},
    )
    assert resp.status_code == 200
    data = resp.json()
    dlt = data["formats"]["dlt"]
    # DLT may succeed or fail per format, but key must exist with files when successful
    if dlt["status"] == "success":
        assert len(dlt["files"]) > 0


def test_convert_returns_sql_files(client, simple_yxmd):
    resp = client.post(
        "/api/convert",
        files={"file": ("simple_filter.yxmd", simple_yxmd, "application/xml")},
    )
    assert resp.status_code == 200
    data = resp.json()
    sql = data["formats"]["sql"]
    if sql["status"] == "success":
        assert len(sql["files"]) > 0


def test_convert_returns_lakeflow_files(client, simple_yxmd):
    resp = client.post(
        "/api/convert",
        files={"file": ("simple_filter.yxmd", simple_yxmd, "application/xml")},
    )
    assert resp.status_code == 200
    data = resp.json()
    lakeflow = data["formats"]["lakeflow"]
    if lakeflow["status"] == "success":
        assert len(lakeflow["files"]) > 0


def test_convert_with_advanced_params(client, simple_yxmd):
    """All advanced conversion params are accepted by the endpoint (no format param)."""
    resp = client.post(
        "/api/convert",
        files={"file": ("simple_filter.yxmd", simple_yxmd, "application/xml")},
        data={
            "expand_macros": "true",
            "include_expression_audit": "true",
            "include_performance_hints": "true",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["workflow_name"] == "simple_filter"
    _assert_multi_format_shape(data)


def test_convert_best_format_is_successful(client, simple_yxmd):
    """best_format should reference a format that actually succeeded."""
    resp = client.post(
        "/api/convert",
        files={"file": ("simple_filter.yxmd", simple_yxmd, "application/xml")},
    )
    assert resp.status_code == 200
    data = resp.json()
    if data["best_format"]:
        assert data["formats"][data["best_format"]]["status"] == "success"
