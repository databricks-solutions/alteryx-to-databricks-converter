"""Migration Project service: the durable estate every step reads and writes.

A project is one migration: its uploaded workflows (stored once), a per-workflow
lifecycle stage, the artifacts each step produces, and estate rollups. See
``docs/migration-project-design.md``.

Persistence uses the server's one connection pool (:mod:`server.services.db`).
Three states, kept distinct because the app treats them differently:

* **No database configured**: every call returns its "unavailable" value (None,
  False, an empty list) and the app runs session-only projects in the browser.
* **Configured but unreachable** (it was down at boot, or a query fails):
  router-facing calls raise :class:`StoreUnavailableError`, which the API answers with
  503, so the UI never mistakes an outage for "this project was deleted" or "you
  have no projects". Initialization is retried lazily, so a database that comes
  up after the app recovers without a restart.
* Best-effort bookkeeping (stage moves after a run, analysis summaries, rollups)
  logs and carries on, because the run itself already succeeded.

Workflow source bytes are stored base64 in the database; Alteryx workflows are
small XML. A ``.yxzp`` is stored as uploaded and re-extracted on read, so its
macros stay with it. Within a project a file name is unique: adding a file with
an existing name replaces that workflow, and adding identical bytes changes
nothing.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
import uuid

from server.services import db
from server.utils.package import is_macro

logger = logging.getLogger("a2d.server.services.project")

_DatabaseError = db.DatabaseError

_initialized = False
_last_init_attempt = 0.0
_INIT_RETRY_SECONDS = 30.0

MAX_NAME_LENGTH = 200

# Lifecycle stages in display order. Moves are forward-only: re-converting a
# deployed workflow updates its artifact but keeps it deployed. "deployed" is set
# by hand (the app never deploys customer pipelines).
STAGES: tuple[str, ...] = ("uploaded", "assessed", "converted", "reviewed", "deployed")


class StoreUnavailableError(RuntimeError):
    """A database is configured but can't be reached right now (API: 503)."""


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

# Columns and constraints added after the first release. Each statement is
# idempotent, so init can run on every start and on old databases alike.
_MIGRATIONS = (
    "CREATE INDEX IF NOT EXISTS idx_project_workflow_project ON project_workflow(project_id)",
    "ALTER TABLE project_workflow ADD COLUMN IF NOT EXISTS size_bytes BIGINT",
    "ALTER TABLE project_workflow ADD COLUMN IF NOT EXISTS content_hash TEXT",
    """UPDATE project_workflow
       SET size_bytes = octet_length(decode(source_b64, 'base64')), content_hash = md5(source_b64)
       WHERE content_hash IS NULL""",
    # Older builds could store two rows with one name; keep the newest.
    """DELETE FROM project_workflow a USING project_workflow b
       WHERE a.project_id = b.project_id AND a.file_name = b.file_name
         AND (a.updated_at, a.id::text) < (b.updated_at, b.id::text)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_project_workflow_name
       ON project_workflow(project_id, file_name)""",
)

# SQL for "move to %(stage)s unless already further along", by STAGES order.
_FORWARD_STAGE_SQL = (
    "CASE WHEN array_position(%(stages)s::text[], stage) < array_position(%(stages)s::text[], %(stage)s::text) "
    "THEN %(stage)s ELSE stage END"
)

_ARTIFACT_COLUMNS = {
    "analysis": "analysis",
    "savings_inputs": "savings_inputs",
    "conversion_refs": "conversion_refs",
    "review_decisions": "review_decisions",
}


def content_hash(content: bytes) -> str:
    """The stored content hash for a workflow's bytes (md5 of its base64 form,
    matching what the database computes for rows written before this column)."""
    return hashlib.md5(base64.b64encode(content), usedforsecurity=False).hexdigest()


# ── availability ───────────────────────────────────────────────────────────


def is_configured() -> bool:
    """True when a database is configured, whether or not it's reachable now."""
    return bool(db.resolve_backend())


def init_db() -> bool:
    """Create or migrate the project tables. Returns True if projects are usable."""
    global _initialized, _last_init_attempt
    _last_init_attempt = time.monotonic()
    pool = db.get_pool()
    if pool is None:
        return False
    try:
        with pool.connection() as conn:
            conn.execute(_CREATE_PROJECT_TABLE)
            conn.execute(_CREATE_WORKFLOW_TABLE)
            for statement in _MIGRATIONS:
                conn.execute(statement)
            conn.commit()
        _initialized = True
        logger.info("Migration-project tables initialized")
        _refresh_stale_rollups()
        return True
    except Exception:
        logger.exception("Failed to initialize migration-project tables")
        return False


def is_available() -> bool:
    """True when projects can be persisted right now.

    If a database is configured but wasn't reachable when the app started, this
    retries initialization (at most every few seconds), so the app recovers
    without a restart.
    """
    if _initialized and db.get_pool() is not None:
        return True
    if is_configured() and time.monotonic() - _last_init_attempt >= _INIT_RETRY_SECONDS:
        return init_db()
    return False


def _pool():
    """The pool when projects are usable, else None (no database configured)."""
    pool = db.get_pool()
    if pool is None or not _initialized:
        return None
    return pool


# ── rollups ────────────────────────────────────────────────────────────────


# Bump when what rollups count changes; init_db recomputes older ones.
# 2: macros aren't workflows; coverage is supported tools over all tools.
ROLLUPS_VERSION = 2


def _rollups_from_workflows(workflows: list[dict]) -> dict:
    """Compute estate rollups from a project's workflows: counts by stage, plus
    estate coverage from their analysis summaries (omitted, not faked, when they
    don't all carry tool counts)."""
    counts = {stage: 0 for stage in STAGES}
    tools = supported = 0
    complete = True  # every analyzed workflow has its tool counts
    analyzed = 0
    workflows = [wf for wf in workflows if not is_macro(str(wf.get("file_name") or ""))]  # macros aren't migrated
    for wf in workflows:
        stage = wf.get("stage", "uploaded")
        if stage in counts:
            counts[stage] += 1
        analysis = wf.get("analysis")
        if isinstance(analysis, dict):
            analyzed += 1
            n, ok = analysis.get("tool_count"), analysis.get("supported_tool_count")
            if isinstance(n, int) and isinstance(ok, int):
                tools += n
                supported += ok
            else:
                complete = False  # stored before tool counts were kept
    rollups: dict = {"version": ROLLUPS_VERSION, "total_workflows": len(workflows), "stage_counts": counts}
    # Estate coverage as Assess shows it (supported tools over all tools); left
    # out until every analyzed workflow has counts, rather than averaged wrongly.
    if analyzed and complete:
        rollups["mean_coverage_pct"] = round(supported / tools * 100.0, 1) if tools else 100.0
    return rollups


def _refresh_rollups(project_id: str, *, touch: bool = True) -> None:
    """Recompute and persist a project's rollups. Best-effort; never raises.

    ``touch=False`` leaves ``updated_at`` alone (a recompute isn't a user change)."""
    pool = _pool()
    if pool is None:
        return
    try:
        with pool.connection() as conn:
            wrows = conn.execute(
                "SELECT file_name, stage, analysis FROM project_workflow WHERE project_id = %s",
                (project_id,),
            ).fetchall()
            rollups = _rollups_from_workflows([{"file_name": w[0], "stage": w[1], "analysis": w[2]} for w in wrows])
            stamp = ", updated_at = NOW()" if touch else ""
            conn.execute(
                f"UPDATE migration_project SET rollups = %s::jsonb{stamp} WHERE id = %s",
                (json.dumps(rollups), project_id),
            )
            conn.commit()
    except _DatabaseError:
        logger.exception("Failed to refresh rollups for project %s", project_id)


def _refresh_stale_rollups() -> None:
    """Recompute rollups stored under an older definition (e.g. ones that counted
    macros as workflows), so the project list is right without waiting for an edit."""
    pool = _pool()
    if pool is None:
        return
    try:
        with pool.connection() as conn:
            stale = conn.execute(
                "SELECT id FROM migration_project WHERE (rollups->>'version') IS DISTINCT FROM %s",
                (str(ROLLUPS_VERSION),),
            ).fetchall()
    except _DatabaseError:
        logger.exception("Failed to find projects with stale rollups")
        return
    for (project_id,) in stale:
        _refresh_rollups(str(project_id), touch=False)
    if stale:
        logger.info("Recomputed rollups for %d project(s)", len(stale))


# ── writing workflows ──────────────────────────────────────────────────────


def _upsert_workflow(conn, project_id: str, file_name: str, content: bytes) -> str:
    """Store one uploaded workflow. Returns "added", "replaced" or "unchanged".

    A file name is unique within a project. Re-uploading ``sales.yxmd`` with new
    bytes means "here's the new version": the row keeps its id, takes the bytes,
    and goes back to ``uploaded`` with its artifacts cleared, because they
    described the old file. Re-uploading identical bytes leaves the row (and its
    review and deployment state) alone.
    """
    encoded = base64.b64encode(content).decode("ascii")
    row = conn.execute(
        """INSERT INTO project_workflow
               (project_id, file_name, source_b64, stage, size_bytes, content_hash)
           VALUES (%(pid)s, %(name)s, %(src)s, 'uploaded', %(size)s, %(hash)s)
           ON CONFLICT (project_id, file_name) DO UPDATE
           SET source_b64 = EXCLUDED.source_b64, size_bytes = EXCLUDED.size_bytes,
               content_hash = EXCLUDED.content_hash, stage = 'uploaded', analysis = NULL,
               savings_inputs = NULL, conversion_refs = NULL, review_decisions = NULL,
               updated_at = NOW()
           WHERE project_workflow.content_hash IS DISTINCT FROM EXCLUDED.content_hash
           RETURNING (xmax = 0) AS inserted""",
        {
            "pid": project_id,
            "name": file_name,
            "src": encoded,
            "size": len(content),
            "hash": content_hash(content),
        },
    ).fetchone()
    if row is None:
        return "unchanged"
    return "added" if row[0] else "replaced"


def _changes(outcomes: list[tuple[str, str]]) -> dict:
    out: dict[str, list[str]] = {"added": [], "replaced": [], "unchanged": []}
    for name, outcome in outcomes:
        out[outcome].append(name)
    return out


def create_project(name: str, files: list[tuple[str, bytes]]) -> dict | None:
    """Create a project and store its workflows in one transaction.

    Returns the project (with a ``changes`` summary), None when no database is
    configured. Raises :class:`StoreUnavailableError` if the database fails.
    """
    pool = _pool()
    if pool is None:
        return None
    project_id = str(uuid.uuid4())
    clean = (name or "").strip()[:MAX_NAME_LENGTH] or "Untitled migration"
    try:
        with pool.connection() as conn:
            conn.execute("INSERT INTO migration_project (id, name) VALUES (%s, %s)", (project_id, clean))
            outcomes = [(fname, _upsert_workflow(conn, project_id, fname, content)) for fname, content in files]
            conn.commit()
    except _DatabaseError as exc:
        logger.exception("Failed to create project")
        raise StoreUnavailableError("Could not save the project; the database isn't responding.") from exc
    _refresh_rollups(project_id)
    project = get_project(project_id)
    if project is not None:
        project["changes"] = _changes(outcomes)
    return project


def add_workflows(project_id: str, files: list[tuple[str, bytes]]) -> dict | None:
    """Add (or replace by name) workflows in an existing project.

    Returns the project with a ``changes`` summary, or None if the project
    doesn't exist (or no database is configured).
    """
    pool = _pool()
    if pool is None:
        return None
    try:
        with pool.connection() as conn:
            exists = conn.execute("SELECT 1 FROM migration_project WHERE id = %s", (project_id,)).fetchone()
            if not exists:
                return None
            outcomes = [(fname, _upsert_workflow(conn, project_id, fname, content)) for fname, content in files]
            conn.commit()
    except _DatabaseError as exc:
        logger.exception("Failed to add workflows to project %s", project_id)
        raise StoreUnavailableError("Could not save the workflows; the database isn't responding.") from exc
    _refresh_rollups(project_id)
    project = get_project(project_id)
    if project is not None:
        project["changes"] = _changes(outcomes)
    return project


# ── reading ────────────────────────────────────────────────────────────────


def list_projects(limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    """List projects (id, name, timestamps, rollups). Returns (items, total)."""
    pool = _pool()
    if pool is None:
        return [], 0
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    try:
        with pool.connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM migration_project").fetchone()
            total = row[0] if row else 0
            rows = conn.execute(
                """SELECT id, name, created_at, updated_at, rollups
                   FROM migration_project ORDER BY updated_at DESC LIMIT %s OFFSET %s""",
                (limit, offset),
            ).fetchall()
    except _DatabaseError as exc:
        logger.exception("Failed to list projects")
        raise StoreUnavailableError("Could not load projects; the database isn't responding.") from exc
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


def get_project(project_id: str) -> dict | None:
    """A project with its workflows (no file bytes), or None if it doesn't exist."""
    pool = _pool()
    if pool is None:
        return None
    try:
        with pool.connection() as conn:
            prow = conn.execute(
                "SELECT id, name, created_at, updated_at, rollups FROM migration_project WHERE id = %s",
                (project_id,),
            ).fetchone()
            if not prow:
                return None
            wrows = conn.execute(
                """SELECT id, file_name, stage, analysis, updated_at, size_bytes, conversion_refs, content_hash
                   FROM project_workflow WHERE project_id = %s ORDER BY file_name""",
                (project_id,),
            ).fetchall()
    except _DatabaseError as exc:
        if _is_bad_id(exc):
            return None
        logger.exception("Failed to get project %s", project_id)
        raise StoreUnavailableError("Could not load the project; the database isn't responding.") from exc
    workflows = [
        {
            "id": str(w[0]),
            "file_name": w[1],
            "stage": w[2],
            "analysis": w[3],
            "updated_at": w[4].isoformat() if w[4] else "",
            "size_bytes": w[5] or 0,
            "conversion": w[6],
            # Changes only when the file's bytes do (not on stage moves), so a
            # client can tell whether a cached analysis still describes it.
            "content_hash": w[7] or "",
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


def _is_bad_id(exc: Exception) -> bool:
    """A malformed UUID in the URL is "not found", not an outage."""
    return "invalid input syntax for type uuid" in str(exc)


def get_workflow_file(project_id: str, workflow_id: str) -> tuple[str, bytes] | None:
    """(file_name, bytes) for a stored workflow, or None if it doesn't exist."""
    pool = _pool()
    if pool is None:
        return None
    try:
        with pool.connection() as conn:
            row = conn.execute(
                "SELECT file_name, source_b64 FROM project_workflow WHERE id = %s AND project_id = %s",
                (workflow_id, project_id),
            ).fetchone()
    except _DatabaseError as exc:
        if _is_bad_id(exc):
            return None
        logger.exception("Failed to read workflow %s", workflow_id)
        raise StoreUnavailableError("Could not read the workflow; the database isn't responding.") from exc
    if not row:
        return None
    return row[0], base64.b64decode(row[1])


def get_workflow_with_macros(
    project_id: str, workflow_id: str
) -> tuple[tuple[str, bytes], list[tuple[str, bytes]]] | None:
    """A stored workflow plus every macro (``.yxmc``) in its project, in one read.

    Returns ``((file_name, bytes), [(macro_name, bytes), ...])``, or None if the
    workflow doesn't exist. A single-workflow step uses this so the workflow's
    macro calls resolve against the project's macros, the same as in a batch run.
    """
    pool = _pool()
    if pool is None:
        return None
    try:
        with pool.connection() as conn:
            rows = conn.execute(
                """SELECT id = %s::uuid, file_name, source_b64 FROM project_workflow
                   WHERE project_id = %s AND (id = %s::uuid OR lower(file_name) LIKE '%%.yxmc')
                   ORDER BY file_name""",
                (workflow_id, project_id, workflow_id),
            ).fetchall()
    except _DatabaseError as exc:
        if _is_bad_id(exc):
            return None
        logger.exception("Failed to read workflow %s with its project's macros", workflow_id)
        raise StoreUnavailableError("Could not read the workflow; the database isn't responding.") from exc
    target = next(((r[1], base64.b64decode(r[2])) for r in rows if r[0]), None)
    if target is None:
        return None
    macros = [(r[1], base64.b64decode(r[2])) for r in rows if r[1].lower().endswith(".yxmc")]
    return target, macros


def get_project_files(project_id: str) -> list[tuple[str, bytes]] | None:
    """(file_name, bytes) for every workflow in a project.

    None when the project doesn't exist (or no database is configured); an empty
    list when it exists but has no workflows.
    """
    pool = _pool()
    if pool is None:
        return None
    try:
        with pool.connection() as conn:
            exists = conn.execute("SELECT 1 FROM migration_project WHERE id = %s", (project_id,)).fetchone()
            if not exists:
                return None
            rows = conn.execute(
                "SELECT file_name, source_b64 FROM project_workflow WHERE project_id = %s ORDER BY file_name",
                (project_id,),
            ).fetchall()
    except _DatabaseError as exc:
        if _is_bad_id(exc):
            return None
        logger.exception("Failed to read files for project %s", project_id)
        raise StoreUnavailableError("Could not read the project's files; the database isn't responding.") from exc
    return [(r[0], base64.b64decode(r[1])) for r in rows]


# ── stage moves and artifacts ──────────────────────────────────────────────


def _check_stage(stage: str) -> None:
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}; valid: {', '.join(STAGES)}")


def advance_workflows_by_name(
    project_id: str, file_names: list[str], stage: str, hashes: dict[str, str] | None = None
) -> int:
    """Move the named workflows forward to ``stage`` (never backward).

    With ``hashes`` (file name -> content hash of the bytes the work used), a
    workflow is only moved if it still holds those bytes, so a run on an old
    version can't mark a newer upload. Best-effort; returns rows touched.
    """
    _check_stage(stage)
    pool = _pool()
    if pool is None or not file_names:
        return 0
    touched = 0
    try:
        with pool.connection() as conn:
            for name in file_names:
                result = conn.execute(
                    f"""UPDATE project_workflow SET stage = {_FORWARD_STAGE_SQL}, updated_at = NOW()
                        WHERE project_id = %(pid)s AND file_name = %(name)s
                          AND (%(hash)s::text IS NULL OR content_hash = %(hash)s::text)""",
                    {
                        "stages": list(STAGES),
                        "stage": stage,
                        "pid": project_id,
                        "name": name,
                        "hash": (hashes or {}).get(name),
                    },
                )
                touched += result.rowcount or 0
            conn.commit()
    except _DatabaseError:
        logger.exception("Failed to advance workflows for project %s", project_id)
        return 0
    if touched:
        _refresh_rollups(project_id)
    return touched


def record_conversion(project_id: str, file_name: str, summary: dict, expected_hash: str | None = None) -> bool:
    """Mark a workflow (by file name) converted and keep a small summary of the
    conversion, so the Convert step shows the last result after a reload.
    Forward-only; with ``expected_hash`` only if the workflow still holds the
    converted bytes. Best-effort."""
    pool = _pool()
    if pool is None:
        return False
    try:
        with pool.connection() as conn:
            result = conn.execute(
                f"""UPDATE project_workflow
                    SET stage = {_FORWARD_STAGE_SQL}, conversion_refs = %(summary)s::jsonb, updated_at = NOW()
                    WHERE project_id = %(pid)s AND file_name = %(name)s
                      AND (%(hash)s::text IS NULL OR content_hash = %(hash)s::text)""",
                {
                    "stages": list(STAGES),
                    "stage": "converted",
                    "summary": json.dumps(summary),
                    "pid": project_id,
                    "name": file_name,
                    "hash": expected_hash,
                },
            )
            conn.commit()
            touched = (result.rowcount or 0) > 0
    except _DatabaseError:
        logger.exception("Failed to record conversion for %s in project %s", file_name, project_id)
        return False
    if touched:
        _refresh_rollups(project_id)
    return touched


def store_analysis(project_id: str, rows: list[dict], hashes: dict[str, str] | None = None) -> int:
    """Save each workflow's analysis summary on its project row, matched by the
    uploaded file name (and, with ``hashes``, only if the bytes are unchanged).
    Feeds the project's average coverage. Best-effort; returns rows stored."""
    pool = _pool()
    if pool is None or not rows:
        return 0
    keep = (
        "coverage_percentage",
        "tool_count",
        "supported_tool_count",
        "complexity_score",
        "complexity_level",
        "migration_priority",
        "estimated_effort",
    )
    stored = 0
    try:
        with pool.connection() as conn:
            for row in rows:
                name = row.get("source_file_name") or row.get("file_name")
                if not name:
                    continue
                summary = {k: row.get(k) for k in keep if k in row}
                result = conn.execute(
                    """UPDATE project_workflow SET analysis = %(summary)s::jsonb, updated_at = NOW()
                       WHERE project_id = %(pid)s AND file_name = %(name)s
                         AND (%(hash)s::text IS NULL OR content_hash = %(hash)s::text)""",
                    {"summary": json.dumps(summary), "pid": project_id, "name": name, "hash": (hashes or {}).get(name)},
                )
                stored += result.rowcount or 0
            conn.commit()
    except _DatabaseError:
        logger.exception("Failed to store analysis for project %s", project_id)
        return 0
    if stored:
        _refresh_rollups(project_id)
    return stored


def set_workflow_stage(
    project_id: str,
    workflow_id: str,
    stage: str,
    *,
    artifact_key: str | None = None,
    artifact: dict | None = None,
) -> bool:
    """Move a workflow forward to ``stage`` and optionally store the artifact that
    stage produced. Returns True if the workflow exists.

    Forward-only: a workflow already past ``stage`` keeps its stage while the
    artifact is still updated. An unknown stage or artifact key is a caller error
    (ValueError).
    """
    _check_stage(stage)
    if artifact_key is not None and artifact_key not in _ARTIFACT_COLUMNS:
        raise ValueError(f"unknown artifact_key {artifact_key!r}")
    pool = _pool()
    if pool is None:
        return False
    params = {"stages": list(STAGES), "stage": stage, "wid": workflow_id, "pid": project_id}
    try:
        with pool.connection() as conn:
            if artifact_key is not None:
                column = _ARTIFACT_COLUMNS[artifact_key]
                result = conn.execute(
                    f"""UPDATE project_workflow
                        SET stage = {_FORWARD_STAGE_SQL}, {column} = %(artifact)s::jsonb, updated_at = NOW()
                        WHERE id = %(wid)s AND project_id = %(pid)s""",
                    {**params, "artifact": json.dumps(artifact)},
                )
            else:
                result = conn.execute(
                    f"""UPDATE project_workflow SET stage = {_FORWARD_STAGE_SQL}, updated_at = NOW()
                        WHERE id = %(wid)s AND project_id = %(pid)s""",
                    params,
                )
            conn.commit()
            if (result.rowcount or 0) == 0:
                return False
    except _DatabaseError as exc:
        if _is_bad_id(exc):
            return False
        logger.exception("Failed to set stage on workflow %s", workflow_id)
        raise StoreUnavailableError("Could not update the workflow; the database isn't responding.") from exc
    _refresh_rollups(project_id)
    return True


# ── project management ─────────────────────────────────────────────────────


def delete_workflow(project_id: str, workflow_id: str) -> bool:
    """Remove one workflow from a project. Returns True if it was removed."""
    pool = _pool()
    if pool is None:
        return False
    try:
        with pool.connection() as conn:
            result = conn.execute(
                "DELETE FROM project_workflow WHERE id = %s AND project_id = %s",
                (workflow_id, project_id),
            )
            conn.commit()
            removed = (result.rowcount or 0) > 0
    except _DatabaseError as exc:
        if _is_bad_id(exc):
            return False
        logger.exception("Failed to delete workflow %s", workflow_id)
        raise StoreUnavailableError("Could not remove the workflow; the database isn't responding.") from exc
    if removed:
        _refresh_rollups(project_id)
    return removed


def rename_project(project_id: str, name: str) -> bool:
    """Rename a project. Returns True if it exists and was renamed."""
    clean = (name or "").strip()
    if not clean:
        raise ValueError("project name must not be empty")
    if len(clean) > MAX_NAME_LENGTH:
        raise ValueError(f"project name must be at most {MAX_NAME_LENGTH} characters")
    pool = _pool()
    if pool is None:
        return False
    try:
        with pool.connection() as conn:
            result = conn.execute(
                "UPDATE migration_project SET name = %s, updated_at = NOW() WHERE id = %s",
                (clean, project_id),
            )
            conn.commit()
            return (result.rowcount or 0) > 0
    except _DatabaseError as exc:
        if _is_bad_id(exc):
            return False
        logger.exception("Failed to rename project %s", project_id)
        raise StoreUnavailableError("Could not rename the project; the database isn't responding.") from exc


def delete_project(project_id: str) -> bool:
    """Delete a project and its workflows (cascade). Returns True if deleted."""
    pool = _pool()
    if pool is None:
        return False
    try:
        with pool.connection() as conn:
            result = conn.execute("DELETE FROM migration_project WHERE id = %s", (project_id,))
            conn.commit()
            return (result.rowcount or 0) > 0
    except _DatabaseError as exc:
        if _is_bad_id(exc):
            return False
        logger.exception("Failed to delete project %s", project_id)
        raise StoreUnavailableError("Could not delete the project; the database isn't responding.") from exc


def advance_uploaded_workflows(project_id: str, stage: str) -> int:
    """Move a project's still-``uploaded`` workflows forward to ``stage``.
    Best-effort; kept for callers that assess a whole project at once."""
    _check_stage(stage)
    pool = _pool()
    if pool is None:
        return 0
    try:
        with pool.connection() as conn:
            result = conn.execute(
                """UPDATE project_workflow SET stage = %s, updated_at = NOW()
                   WHERE project_id = %s AND stage = 'uploaded'""",
                (stage, project_id),
            )
            conn.commit()
            advanced = result.rowcount or 0
    except _DatabaseError:
        logger.exception("Failed to advance workflows for project %s", project_id)
        return 0
    if advanced:
        _refresh_rollups(project_id)
    return advanced
