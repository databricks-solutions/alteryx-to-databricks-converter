"""The project store against a real Postgres.

The unit tests mock the pool, which can show degradation but not SQL semantics:
forward-only stages, replace-by-name, unchanged re-uploads, content-hash guards,
cascades. These run against a real database and are skipped unless one is given:

    A2D_TEST_DATABASE_URL=postgresql://... pytest tests/integration/test_project_store_postgres.py

Each test works in a fresh project and deletes it afterwards, so a shared
development database is safe to point at.
"""

from __future__ import annotations

import os

import pytest

DB_URL = os.environ.get("A2D_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DB_URL, reason="set A2D_TEST_DATABASE_URL to run against a real Postgres"),
]


@pytest.fixture(scope="module")
def store():
    from server.services import db
    from server.services import project as project_service
    from server.settings import settings

    saved = (settings.database_url, settings.db_backend, db._pool, project_service._initialized)
    settings.database_url, settings.db_backend, db._pool = DB_URL, "postgres", None
    assert project_service.init_db()
    yield project_service
    db.close_pool()
    settings.database_url, settings.db_backend, db._pool, project_service._initialized = saved


@pytest.fixture()
def project(store):
    p = store.create_project("integration test", [("a.yxmd", b"<A v='1'/>"), ("b.yxmd", b"<B/>")])
    yield p
    store.delete_project(p["id"])


def _wf(store, project_id: str, name: str) -> dict:
    return next(w for w in store.get_project(project_id)["workflows"] if w["file_name"] == name)


def test_create_reports_changes_sizes_and_hashes(store, project):
    assert project["changes"] == {"added": ["a.yxmd", "b.yxmd"], "replaced": [], "unchanged": []}
    a = _wf(store, project["id"], "a.yxmd")
    assert a["size_bytes"] == len(b"<A v='1'/>")
    assert a["content_hash"] == store.content_hash(b"<A v='1'/>")


def test_stages_only_move_forward(store, project):
    a = _wf(store, project["id"], "a.yxmd")
    assert store.set_workflow_stage(project["id"], a["id"], "deployed")
    assert store.set_workflow_stage(
        project["id"], a["id"], "converted", artifact_key="conversion_refs", artifact={"coverage": 50}
    )
    a = _wf(store, project["id"], "a.yxmd")
    assert a["stage"] == "deployed"
    assert a["conversion"] == {"coverage": 50}  # the artifact still updates


def test_identical_reupload_changes_nothing(store, project):
    a = _wf(store, project["id"], "a.yxmd")
    store.set_workflow_stage(project["id"], a["id"], "reviewed")
    result = store.add_workflows(project["id"], [("a.yxmd", b"<A v='1'/>")])
    assert result["changes"]["unchanged"] == ["a.yxmd"]
    assert _wf(store, project["id"], "a.yxmd")["stage"] == "reviewed"


def test_new_bytes_replace_and_start_over(store, project):
    a = _wf(store, project["id"], "a.yxmd")
    store.record_conversion(project["id"], "a.yxmd", {"coverage": 90})
    result = store.add_workflows(project["id"], [("a.yxmd", b"<A v='2'/>")])
    assert result["changes"]["replaced"] == ["a.yxmd"]
    a2 = _wf(store, project["id"], "a.yxmd")
    assert a2["id"] == a["id"]
    assert a2["stage"] == "uploaded"
    assert a2["conversion"] is None
    assert len(result["workflows"]) == 2  # no duplicate row


def test_a_run_on_old_bytes_does_not_mark_the_new_version(store, project):
    old_hash = store.content_hash(b"<A v='1'/>")
    store.add_workflows(project["id"], [("a.yxmd", b"<A v='2'/>")])
    assert store.record_conversion(project["id"], "a.yxmd", {"coverage": 1}, old_hash) is False
    assert _wf(store, project["id"], "a.yxmd")["stage"] == "uploaded"
    assert store.advance_workflows_by_name(project["id"], ["a.yxmd"], "assessed", {"a.yxmd": old_hash}) == 0


def test_analysis_is_stored_and_feeds_the_rollup(store, project):
    rows = [
        {
            "source_file_name": "a.yxmd",
            "file_name": "primary.yxwz",
            "coverage_percentage": 80.0,
            "tool_count": 10,
            "supported_tool_count": 8,
        },
        {"file_name": "b.yxmd", "coverage_percentage": 100.0, "tool_count": 30, "supported_tool_count": 30},
    ]
    assert store.store_analysis(project["id"], rows) == 2
    # Supported tools over all tools: 38 of 40.
    assert store.get_project(project["id"])["rollups"]["mean_coverage_pct"] == 95.0


def test_macros_are_not_counted_as_workflows(store):
    p = store.create_project("with a macro", [("a.yxmd", b"<A/>"), ("Cleanse.yxmc", b"<M/>")])
    try:
        rollups = store.get_project(p["id"])["rollups"]
        assert rollups["total_workflows"] == 1
        assert sum(rollups["stage_counts"].values()) == 1
    finally:
        store.delete_project(p["id"])


def test_startup_recomputes_rollups_stored_under_an_older_definition(store):
    from server.services import db

    p = store.create_project("old rollups", [("a.yxmd", b"<A/>"), ("Cleanse.yxmc", b"<M/>")])
    try:
        with db.get_pool().connection() as conn:  # what an older version stored
            conn.execute(
                "UPDATE migration_project SET rollups = %s::jsonb, updated_at = '2026-01-01' WHERE id = %s",
                ('{"total_workflows": 2, "stage_counts": {"uploaded": 2}}', p["id"]),
            )
            conn.commit()
        assert store.init_db()
        got = store.get_project(p["id"])
        assert got["rollups"]["total_workflows"] == 1
        assert got["rollups"]["version"] == store.ROLLUPS_VERSION
        assert got["updated_at"].startswith("2026-01-01")  # a recompute isn't a user edit
    finally:
        store.delete_project(p["id"])


def test_unique_names_are_enforced_by_the_database(store, project):
    from server.services import db

    with pytest.raises(store._DatabaseError), db.get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO project_workflow (project_id, file_name, source_b64) VALUES (%s, 'a.yxmd', 'eA==')",
            (project["id"],),
        )


def test_delete_cascades_and_bad_ids_are_not_found(store):
    p = store.create_project("to delete", [("a.yxmd", b"<A/>")])
    wid = p["workflows"][0]["id"]
    assert store.delete_project(p["id"])
    assert store.get_project(p["id"]) is None
    assert store.get_workflow_file(p["id"], wid) is None
    assert store.get_project("not-a-uuid") is None


def test_a_workflow_comes_with_its_projects_macros(store):
    p = store.create_project(
        "macros",
        [("main.yxmd", b"<M/>"), ("Cleanse.YXMC", b"<C/>"), ("other.yxmd", b"<O/>"), ("Helper.yxmc", b"<H/>")],
    )
    try:
        main_id = next(w["id"] for w in p["workflows"] if w["file_name"] == "main.yxmd")
        (name, content), macros = store.get_workflow_with_macros(p["id"], main_id)
        assert (name, content) == ("main.yxmd", b"<M/>")
        assert sorted(macros) == [("Cleanse.YXMC", b"<C/>"), ("Helper.yxmc", b"<H/>")]
        # A macro asked for by itself is both the workflow and one of the macros.
        macro_id = next(w["id"] for w in p["workflows"] if w["file_name"] == "Helper.yxmc")
        (name, _), macros = store.get_workflow_with_macros(p["id"], macro_id)
        assert name == "Helper.yxmc" and len(macros) == 2
        assert store.get_workflow_with_macros(p["id"], "00000000-0000-0000-0000-000000000000") is None
        assert store.get_workflow_with_macros(p["id"], "not-a-uuid") is None
    finally:
        store.delete_project(p["id"])
