"""Usage tracking against a real Postgres (skipped unless A2D_TEST_DATABASE_URL is set).

    A2D_TEST_DATABASE_URL=postgresql://... pytest tests/integration/test_usage_postgres.py

Uses its own tables' rows and removes them afterwards, except the usage table
itself, which it creates if missing.
"""

from __future__ import annotations

import os
import uuid

import pytest

DB_URL = os.environ.get("A2D_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DB_URL, reason="set A2D_TEST_DATABASE_URL to run against a real Postgres"),
]

ME = f"usage-test-{uuid.uuid4().hex[:8]}@example.com"


@pytest.fixture(scope="module")
def usage():
    from server.services import db
    from server.services import project as project_service
    from server.services import usage as usage_service
    from server.settings import settings

    saved = (settings.database_url, settings.db_backend, db._pool, settings.usage_admins, settings.usage_tracking)
    settings.database_url, settings.db_backend, db._pool = DB_URL, "postgres", None
    settings.usage_admins, settings.usage_tracking = ME, True
    assert project_service.init_db() and usage_service.init_db()
    with db.get_pool().connection() as conn:
        # What older builds wrote, so the page can show history from before tracking.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS conversion_history (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(), workflow_name TEXT NOT NULL,
                output_format TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW(), node_count INT NOT NULL,
                edge_count INT NOT NULL, coverage_percentage FLOAT, warnings JSONB DEFAULT '[]',
                files JSONB NOT NULL, dag_data JSONB, stats JSONB)"""
        )
        conn.execute(
            "INSERT INTO conversion_history (workflow_name, output_format, created_at, node_count, edge_count, "
            "coverage_percentage, files) VALUES ('old.yxmd', 'pyspark', '2026-05-02', 10, 9, 80.0, '[]'), "
            "('old.yxmd', 'sql', '2026-06-10', 10, 9, 90.0, '[]')"
        )
        conn.commit()
    yield usage_service
    with db.get_pool().connection() as conn:
        conn.execute("DELETE FROM usage_event WHERE user_email = %s OR user_email IS NULL", (ME,))
        conn.execute("DELETE FROM conversion_history WHERE workflow_name = 'old.yxmd'")
        conn.commit()
    db.close_pool()
    (settings.database_url, settings.db_backend, db._pool, settings.usage_admins, settings.usage_tracking) = saved


def test_events_add_up(usage):
    usage.record("open_app", user=ME.upper(), status=200)
    usage.record("convert", user=ME, status=200, duration_ms=120, details={"workflows": 1, "coverage": 90})
    usage.record("convert_batch", user=ME, status=200, project_id="p1", details={"workflows": 4})
    usage.record("convert", user=ME, status=422, details={"workflows": 1})  # a failed one isn't counted as converted
    usage.record("ai_complete", user=ME, status=200, details={"steps": 5, "completed": 5})
    s = usage.summary(30)
    assert s["totals"]["workflows_converted"] >= 5 and s["totals"]["ai_runs"] >= 1
    me = next(u for u in s["by_user"] if u["user"] == ME)  # emails are stored lower-case
    assert (me["events"], me["conversions"], me["ai_runs"]) == (5, 3, 1)
    assert s["by_action"]["convert"] >= 2
    assert all(e["action"] != "open_app" for e in s["recent"])
    assert next(e for e in s["recent"] if e["action"] == "convert_batch")["details"] == {"workflows": 4}


def test_history_from_before_tracking(usage):
    h = usage.summary(30)["history"]
    assert h["conversions"] >= 2 and h["by_format"]["sql"] >= 1
    assert {"month": "2026-05", "conversions": 1, "workflows": 1} in h["by_month"] or h["conversions"] > 2


def test_saved_projects_are_counted(usage):
    assert usage.summary(30)["projects"]["projects"] >= 0


def test_a_reader_gets_read_only_access(usage):
    from server.services import db
    from server.settings import settings

    reader = f"reader-{uuid.uuid4().hex[:6]}@example.com"
    with db.get_pool().connection() as conn:
        conn.execute(f'CREATE ROLE "{reader}" LOGIN')
        conn.commit()
    settings.db_readers = reader
    try:
        usage.init_db()
        with db.get_pool().connection() as conn:
            row = conn.execute(
                "SELECT has_table_privilege(%s, 'usage_event', 'SELECT'), "
                "has_table_privilege(%s, 'usage_event', 'INSERT')",
                (reader, reader),
            ).fetchone()
        assert row == (True, False)
    finally:
        settings.db_readers = ""
        with db.get_pool().connection() as conn:
            conn.execute(f'DROP OWNED BY "{reader}"')
            conn.execute(f'DROP ROLE "{reader}"')
            conn.commit()


def test_the_api_only_answers_admins(usage):
    from fastapi.testclient import TestClient
    from server.main import app

    client = TestClient(app)
    assert client.get("/api/usage").status_code == 403
    assert client.get("/api/usage", headers={"X-Forwarded-Email": "someone@example.com"}).status_code == 403
    ok = client.get("/api/usage", headers={"X-Forwarded-Email": ME})
    assert ok.status_code == 200 and ok.json()["tracking"] is True
    access = client.get("/api/usage/access", headers={"X-Forwarded-Email": ME}).json()
    assert access == {"user": ME, "allowed": True, "admins_configured": True, "tracking": True, "database": True}
