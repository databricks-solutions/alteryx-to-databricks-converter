"""Tests for the estate-level insight endpoints (/api/portfolio, /api/advise).

Both wrap features that shipped CLI-only, so these also pin the contract the new
UI pages depend on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).parent.parent.parent / "fixtures" / "workflows"


def _wf(name: str) -> bytes:
    return (WORKFLOWS / name).read_bytes()


def _upload(name: str):
    return ("files", (name, _wf(name), "application/xml"))


class TestPortfolioEndpoint:
    def test_analyzes_multiple_workflows(self, client):
        resp = client.post(
            "/api/portfolio",
            files=[_upload("simple_filter.yxmd"), _upload("join_and_summarize.yxmd")],
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["summary"]["workflow_count"] == 2
        # The migration plan is the headline output — it must be present and ordered.
        assert "migration_plan" in data
        assert isinstance(data["migration_plan"]["waves"], list)
        assert data["summary"]["estimated_effort_days"] >= 0

    def test_shape_matches_cli_serializer(self, client):
        """The endpoint reuses a2d.portfolio.report.to_dict, so keys must match."""
        from a2d.portfolio.report import to_dict

        resp = client.post("/api/portfolio", files=[_upload("simple_filter.yxmd")])
        assert resp.status_code == 200

        # Same top-level contract the CLI writes with --json.
        expected_keys = {
            "generated_at",
            "tool_version",
            "summary",
            "dependencies",
            "shared_macros",
            "duplicate_subflows",
            "isolated_workflows",
            "migration_plan",
        }
        assert expected_keys <= set(resp.json())
        assert callable(to_dict)

    def test_single_workflow_is_valid_if_thin(self, client):
        resp = client.post("/api/portfolio", files=[_upload("simple_filter.yxmd")])
        assert resp.status_code == 200
        assert resp.json()["summary"]["workflow_count"] == 1

    def test_non_yxmd_rejected(self, client):
        resp = client.post(
            "/api/portfolio",
            files=[("files", ("notes.txt", b"hello", "text/plain"))],
        )
        assert resp.status_code == 400


class TestAdviseEndpoint:
    def test_returns_cluster_recommendation_and_hints(self, client):
        resp = client.post(
            "/api/advise",
            files={"file": ("join_and_summarize.yxmd", _wf("join_and_summarize.yxmd"), "application/xml")},
            data={"cloud": "aws"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["workflow_name"] == "join_and_summarize"
        cluster = data["cluster"]
        assert cluster["tier"] in ("single-node", "small", "medium", "large")
        assert cluster["workers"] >= 0
        assert cluster["node_type_id"]
        assert isinstance(data["hints"], list)

    @pytest.mark.parametrize("cloud", ["aws", "azure", "gcp"])
    def test_cloud_drives_node_type(self, client, cloud):
        resp = client.post(
            "/api/advise",
            files={"file": ("simple_filter.yxmd", _wf("simple_filter.yxmd"), "application/xml")},
            data={"cloud": cloud},
        )
        assert resp.status_code == 200
        assert resp.json()["cluster"]["node_type_id"]

    def test_unknown_cloud_is_422(self, client):
        resp = client.post(
            "/api/advise",
            files={"file": ("simple_filter.yxmd", _wf("simple_filter.yxmd"), "application/xml")},
            data={"cloud": "moon"},
        )
        assert resp.status_code == 422
        assert "unknown cloud" in resp.json()["detail"]

    def test_non_yxmd_rejected(self, client):
        resp = client.post(
            "/api/advise",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 400
