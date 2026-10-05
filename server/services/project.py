"""Migration Project service — the durable estate every screen reads and writes.

A project is one migration: its uploaded workflows (stored once), a per-workflow
lifecycle stage, the artifacts each screen produces, and estate rollups. See
``docs/migration-project-design.md``.

Persistence reuses the history service's connection pool (one pool for the whole
server) and its graceful-degradation discipline: with no database configured
every call returns the "unavailable" value and the app falls back to its
in-session stores, exactly as it behaves today. A database outage degrades
rather than 500s; a genuine programming error still surfaces.

Phase 1 (foundation): the project object, its API, and tests. Workflow source
bytes are stored in the database (base64) — Alteryx workflows/macros are small
XML, and this keeps the bytes durable across app restarts without a separate
object store. A ``.yxzp`` is stored as its original upload and re-materialized on
read (extractor runs again, macros co-located), so the macro-resolution path is
preserved. Large-package storage in a Unity Catalog Volume is a documented
follow-on.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid

from server.services import history

logger = logging.getLogger("a2d.server.services.project")

# Reuse the history service's pool and DB-error type: one pool per server, and no
# second copy of the backend-resolution rule. project owns only its own schema
# state (`_initialized`) and tables.
_DatabaseError = history._DatabaseError

_initialized = False

# Lifecycle stages in display order. Forward-only for presentation; a workflow
# can be re-converted/re-reviewed (updates artifact + timestamp) without moving
# backward. "deployed" is set manually (the app never deploys customer pipelines).
STAGES: tuple[str, ...] = ("uploaded", "assessed", "converted", "reviewed", "deployed")

_CREATE_PROJECT_TABLE = """
CREATE TABLE IF NOT EXISTS migration_project (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    rollups JSONB DEFAULT '{}'
);
"""

_CREATE_WORKFLOW_TABLE = """
CREATE TABLE IF NOT EXISTS project_workflow (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES migration_project(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    source_b64 TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'uploaded',
    analysis JSONB,
    savings_inputs JSONB,
    conversion_refs JSONB,
    review_decisions JSONB,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
"""

_CREATE_WORKFLOW_INDEX = """
CREATE INDEX IF NOT EXISTS idx_project_workflow_project ON project_workflow(project_id);
"""


def init_db() -> bool:
    """Create the project tables if absent. Returns True if a database is available."""
    global _initialized
    pool = history._get_pool()
    if pool is None:
        return False
    try:
        with pool.connection() as conn:
            conn.execute(_CREATE_PROJECT_TABLE)
            conn.execute(_CREATE_WORKFLOW_TABLE)
            conn.execute(_CREATE_WORKFLOW_INDEX)
            conn.commit()
        _initialized = True
        logger.info("Migration-project tables initialized")
        return True
    except Exception:
        logger.exception("Failed to initialize migration-project tables")
        return False


def is_available() -> bool:
    """True when projects can be persisted (schema initialized and pool present)."""
    return _initialized and history._get_pool() is not None


def _rollups_from_workflows(workflows: list[dict]) -> dict:
    """Compute estate rollups from a project's workflows.

    Deterministic and cheap: counts by stage, plus coverage averaged over the
    workflows that have an analysis artifact. Savings/effort are added when those
    artifacts are wired in (Phase 2); absent, they are omitted rather than faked.
    """
    counts = {stage: 0 for stage in STAGES}
    coverages: list[float] = []
    for wf in workflows:
        stage = wf.get("stage", "uploaded")
        if stage in counts:
            counts[stage] += 1
        analysis = wf.get("analysis")
        if isinstance(analysis, dict):
            cov = analysis.get("coverage_percentage")
            if isinstance(cov, int | float):
                coverages.append(float(cov))
    rollups: dict = {"total_workflows": len(workflows), "stage_counts": counts}
    if coverages:
        rollups["mean_coverage_pct"] = round(sum(coverages) / len(coverages), 1)
    return rollups


def create_project(name: str, files: list[tuple[str, bytes]]) -> dict | None:
    """Create a project and store its uploaded workflows. Returns the project dict.

    Returns None when projects are unavailable (no backend) so the router answers
    a clear "unavailable" rather than 500. A database outage degrades to None;
    programming errors still propagate.
    """
    pool = history._get_pool()
    if pool is None or not _initialized:
        return None

    project_id = str(uuid.uuid4())
    try:
        with pool.connection() as conn:
            conn.execute(
                "INSERT INTO migration_project (id, name) VALUES (%s, %s)",
                (project_id, name or "Untitled migration"),
            )
            for file_name, content in files:
                conn.execute(
                    """INSERT INTO project_workflow (project_id, file_name, source_b64, stage)
                       VALUES (%s, %s, %s, 'uploaded')""",
                    (project_id, file_name, base64.b64encode(content).decode("ascii")),
                )
            conn.commit()
        _refresh_rollups(project_id)
        return get_project(project_id)
    except _DatabaseError:
        logger.exception("Failed to create project")
        return None


def add_workflows(project_id: str, files: list[tuple[str, bytes]]) -> dict | None:
    """Add uploaded workflows to an existing project. Returns the updated project."""
    pool = history._get_pool()
    if pool is None or not _initialized:
        return None
    try:
        with pool.connection() as conn:
            exists = conn.execute("SELECT 1 FROM migration_project WHERE id = %s", (project_id,)).fetchone()
            if not exists:
                return None
            for file_name, content in files:
                conn.execute(
                    """INSERT INTO project_workflow (project_id, file_name, source_b64, stage)
                       VALUES (%s, %s, %s, 'uploaded')""",
                    (project_id, file_name, base64.b64encode(content).decode("ascii")),
                )
            conn.commit()
        _refresh_rollups(project_id)
        return get_project(project_id)
    except _DatabaseError:
        logger.exception("Failed to add workflows to project %s", project_id)
        return None


def list_projects(limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    """List projects (summary: id, name, timestamps, rollups). Returns (items, total)."""
    pool = history._get_pool()
    if pool is None or not _initialized:
        return [], 0
    try:
        with pool.connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM migration_project").fetchone()
            total = row[0] if row else 0
            rows = conn.execute(
                """SELECT id, name, created_at, updated_at, rollups
                   FROM migration_project ORDER BY updated_at DESC LIMIT %s OFFSET %s""",
                (limit, offset),
            ).fetchall()
        items = [
            {
                "id": str(r[0]),
                "name": r[1],
                "created_at": r[2].isoformat() if r[2] else "",
                "updated_at": r[3].isoformat() if r[3] else "",
                "rollups": r[4] or {},
            }
            for r in rows
        ]
        return items, total
    except _DatabaseError:
        logger.exception("Failed to list projects")
        return [], 0


def get_project(project_id: str) -> dict | None:
    """Fetch a project with its workflows (no file bytes). None if absent/unavailable."""
    pool = history._get_pool()
    if pool is None or not _initialized:
        return None
    try:
        with pool.connection() as conn:
            prow = conn.execute(
                """SELECT id, name, created_at, updated_at, rollups
                   FROM migration_project WHERE id = %s""",
                (project_id,),
            ).fetchone()
            if not prow:
                return None
            wrows = conn.execute(
                """SELECT id, file_name, stage, analysis, updated_at
                   FROM project_workflow WHERE project_id = %s ORDER BY file_name""",
                (project_id,),
            ).fetchall()
        workflows = [
            {
                "id": str(w[0]),
                "file_name": w[1],
                "stage": w[2],
                "analysis": w[3],
                "updated_at": w[4].isoformat() if w[4] else "",
            }
            for w in wrows
        ]
        return {
            "id": str(prow[0]),
            "name": prow[1],
            "created_at": prow[2].isoformat() if prow[2] else "",
            "updated_at": prow[3].isoformat() if prow[3] else "",
            "rollups": prow[4] or {},
            "workflows": workflows,
        }
    except _DatabaseError:
        logger.exception("Failed to get project %s", project_id)
        return None


def get_workflow_file(project_id: str, workflow_id: str) -> tuple[str, bytes] | None:
    """Return (file_name, bytes) for a stored workflow, so any screen reads it
    without a re-upload. None if absent/unavailable."""
    pool = history._get_pool()
    if pool is None or not _initialized:
        return None
    try:
        with pool.connection() as conn:
            row = conn.execute(
                """SELECT file_name, source_b64 FROM project_workflow
                   WHERE id = %s AND project_id = %s""",
                (workflow_id, project_id),
            ).fetchone()
        if not row:
            return None
        return row[0], base64.b64decode(row[1])
    except _DatabaseError:
        logger.exception("Failed to read workflow %s", workflow_id)
        return None


_ARTIFACT_COLUMNS = {
    "analysis": "analysis",
    "savings_inputs": "savings_inputs",
    "conversion_refs": "conversion_refs",
    "review_decisions": "review_decisions",
}


def set_workflow_stage(
    project_id: str,
    workflow_id: str,
    stage: str,
    *,
    artifact_key: str | None = None,
    artifact: dict | None = None,
) -> bool:
    """Advance a workflow's stage and optionally store the artifact that stage
    produced, then refresh the project's rollups. Returns True on success.

    ``stage`` must be a known lifecycle stage; an unknown value is a programming
    error (raises ValueError) rather than silently writing garbage. ``artifact_key``
    must be one of the known artifact columns.
    """
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}; valid: {', '.join(STAGES)}")
    if artifact_key is not None and artifact_key not in _ARTIFACT_COLUMNS:
        raise ValueError(f"unknown artifact_key {artifact_key!r}")

    pool = history._get_pool()
    if pool is None or not _initialized:
        return False
    try:
        with pool.connection() as conn:
            if artifact_key is not None:
                column = _ARTIFACT_COLUMNS[artifact_key]
                result = conn.execute(
                    f"""UPDATE project_workflow
                        SET stage = %s, {column} = %s::jsonb, updated_at = NOW()
                        WHERE id = %s AND project_id = %s""",
                    (stage, json.dumps(artifact), workflow_id, project_id),
                )
            else:
                result = conn.execute(
                    """UPDATE project_workflow
                       SET stage = %s, updated_at = NOW()
                       WHERE id = %s AND project_id = %s""",
                    (stage, workflow_id, project_id),
                )
            conn.commit()
            if (result.rowcount or 0) == 0:
                return False
        _refresh_rollups(project_id)
        return True
    except _DatabaseError:
        logger.exception("Failed to set stage on workflow %s", workflow_id)
        return False


def delete_project(project_id: str) -> bool:
    """Delete a project and its workflows (cascade). Returns True if deleted."""
    pool = history._get_pool()
    if pool is None or not _initialized:
        return False
    try:
        with pool.connection() as conn:
            result = conn.execute("DELETE FROM migration_project WHERE id = %s", (project_id,))
            conn.commit()
            return (result.rowcount or 0) > 0
    except _DatabaseError:
        logger.exception("Failed to delete project %s", project_id)
        return False


def _refresh_rollups(project_id: str) -> None:
    """Recompute and persist a project's rollups. Best-effort; never raises."""
    pool = history._get_pool()
    if pool is None or not _initialized:
        return
    try:
        with pool.connection() as conn:
            wrows = conn.execute(
                "SELECT stage, analysis FROM project_workflow WHERE project_id = %s",
                (project_id,),
            ).fetchall()
            workflows = [{"stage": w[0], "analysis": w[1]} for w in wrows]
            rollups = _rollups_from_workflows(workflows)
            conn.execute(
                "UPDATE migration_project SET rollups = %s::jsonb, updated_at = NOW() WHERE id = %s",
                (json.dumps(rollups), project_id),
            )
            conn.commit()
    except _DatabaseError:
        logger.exception("Failed to refresh rollups for project %s", project_id)
