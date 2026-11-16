"""Usage: who used the app for what, kept in the app's database.

Each tracked request (a conversion, an analysis, a review, an AI run, a project
change, opening the app) is one ``usage_event`` row: when, the signed-in user's
email (Databricks Apps passes it in ``X-Forwarded-Email``), the action, the
response status, how long it took and a few details a route adds (how many
workflows, the coverage). Recording runs after the response and never fails a
request; with no database, or ``A2D_USAGE_TRACKING=false``, nothing is recorded.

The Usage page reads :func:`summary`. It also shows the ``conversion_history``
table older builds wrote (one row per conversion, with no user), so the history
from before tracking isn't lost.

Only the emails in ``A2D_USAGE_ADMINS`` can read it, since it lists colleagues.
``A2D_DB_READERS`` gets read-only SQL access (SELECT) to the app's tables at
startup, for querying them directly.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from server.services import db
from server.settings import settings

logger = logging.getLogger("a2d.server.services.usage")

_CREATE = """
CREATE TABLE IF NOT EXISTS usage_event (
    id BIGSERIAL PRIMARY KEY,
    at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_email TEXT,
    action TEXT NOT NULL,
    status INT,
    duration_ms INT,
    project_id TEXT,
    details JSONB
);
"""
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_usage_event_at ON usage_event(at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_usage_event_user ON usage_event(user_email)",
)
_RETRY_SECONDS = 60.0

_initialized = False
_last_attempt = float("-inf")


def _emails(value: str) -> list[str]:
    return [e.strip().lower() for e in (value or "").split(",") if e.strip()]


def admins() -> list[str]:
    return _emails(settings.usage_admins)


def can_view(user: str | None) -> bool:
    """Whether ``user`` may see the Usage page (it lists colleagues' emails)."""
    return user is not None and user.lower() in admins()


def init_db() -> bool:
    """Create the usage table, and grant read access to ``A2D_DB_READERS``."""
    global _initialized, _last_attempt
    _last_attempt = time.monotonic()
    pool = db.get_pool()
    if pool is None:
        return False
    try:
        with pool.connection() as conn:
            conn.execute(_CREATE)
            for statement in _INDEXES:
                conn.execute(statement)
            conn.commit()
        _initialized = True
    except Exception:
        logger.exception("Failed to initialize the usage table")
        return False
    _grant_readers(pool)
    return True


def _grant_readers(pool) -> None:
    """Read-only access for each configured reader. Best-effort: a reader whose
    Postgres role doesn't exist yet is logged and skipped."""
    readers = _emails(settings.db_readers)
    if not readers:
        return
    from psycopg import sql

    for reader in readers:
        role = sql.Identifier(reader)
        statements = (
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role),
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(role),
            sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {}").format(role),
        )
        try:
            with pool.connection() as conn:
                for statement in statements:
                    conn.execute(statement)
                conn.commit()
            logger.info("Granted read-only access to %s", reader)
        except Exception as exc:
            logger.warning("Couldn't grant read-only access to %s (does its Postgres role exist?): %s", reader, exc)


def _ready():
    """The pool when usage can be recorded, else None."""
    if not settings.usage_tracking:
        return None
    if not _initialized and db.resolve_backend() and time.monotonic() - _last_attempt >= _RETRY_SECONDS:
        init_db()
    return db.get_pool() if _initialized else None


def record(
    action: str,
    *,
    user: str | None,
    status: int | None = None,
    duration_ms: int | None = None,
    project_id: str | None = None,
    details: dict | None = None,
) -> None:
    """Store one event. Never raises: usage must not break the app."""
    try:
        pool = _ready()
        if pool is None:
            return
        with pool.connection() as conn:
            conn.execute(
                "INSERT INTO usage_event (user_email, action, status, duration_ms, project_id, details) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb)",
                (
                    (user or "").lower() or None,
                    action,
                    status,
                    duration_ms,
                    project_id,
                    json.dumps(details or {}, default=str),
                ),
            )
            conn.commit()
    except Exception:
        logger.warning("Couldn't record usage event %s", action, exc_info=True)


# ── reading it back ────────────────────────────────────────────────────────


def _iso(value) -> str | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value) if value is not None else None


def _table_exists(conn, name: str) -> bool:
    row = conn.execute("SELECT to_regclass(%s)", (f"public.{name}",)).fetchone()
    return bool(row and row[0])


def summary(days: int = 30) -> dict:
    """What the Usage page shows, for the last ``days`` days (plus all-time totals)."""
    pool = db.get_pool()
    out: dict = {
        "days": days,
        "tracking": bool(settings.usage_tracking),
        "database": pool is not None,
        "since": None,
        "totals": {},
        "by_action": {},
        "by_day": [],
        "by_user": [],
        "recent": [],
        "projects": None,
        "history": None,
    }
    if pool is None:
        return out
    if not _initialized:
        init_db()
    with pool.connection() as conn:
        if _table_exists(conn, "usage_event"):
            window = "at >= NOW() - make_interval(days => %s)"
            first = conn.execute("SELECT MIN(at), COUNT(*) FROM usage_event").fetchone()
            out["since"] = _iso(first[0]) if first else None
            totals = conn.execute(
                f"""SELECT COUNT(*), COUNT(DISTINCT user_email),
                       COALESCE(SUM(CASE WHEN action IN ('convert', 'convert_batch') AND status < 400
                                         THEN COALESCE((details->>'workflows')::int, 1) END), 0),
                       COUNT(*) FILTER (WHERE action IN ('ai_complete', 'ai_suggest') AND status < 400)
                    FROM usage_event WHERE {window}""",
                (days,),
            ).fetchone()
            out["totals"] = {
                "events": totals[0],
                "people": totals[1],
                "workflows_converted": int(totals[2] or 0),
                "ai_runs": totals[3],
                "events_all_time": first[1] if first else 0,
            }
            out["by_action"] = dict(
                conn.execute(
                    f"SELECT action, COUNT(*) FROM usage_event WHERE {window} GROUP BY action ORDER BY 2 DESC",
                    (days,),
                ).fetchall()
            )
            out["by_day"] = [
                {"day": str(d), "events": n, "people": p, "conversions": int(c or 0)}
                for d, n, p, c in conn.execute(
                    f"""SELECT (at AT TIME ZONE 'UTC')::date, COUNT(*), COUNT(DISTINCT user_email),
                           COALESCE(SUM(CASE WHEN action IN ('convert', 'convert_batch') AND status < 400
                                             THEN COALESCE((details->>'workflows')::int, 1) END), 0)
                        FROM usage_event WHERE {window} GROUP BY 1 ORDER BY 1""",
                    (days,),
                ).fetchall()
            ]
            out["by_user"] = [
                {"user": u, "events": n, "conversions": c, "ai_runs": a, "first_seen": _iso(f), "last_seen": _iso(last)}
                for u, n, c, a, f, last in conn.execute(
                    f"""SELECT COALESCE(user_email, '(unknown)'), COUNT(*),
                           COUNT(*) FILTER (WHERE action IN ('convert', 'convert_batch')),
                           COUNT(*) FILTER (WHERE action IN ('ai_complete', 'ai_suggest')),
                           MIN(at), MAX(at)
                        FROM usage_event WHERE {window} GROUP BY 1 ORDER BY 2 DESC LIMIT 200""",
                    (days,),
                ).fetchall()
            ]
            out["recent"] = [
                {"at": _iso(at), "user": u, "action": a, "status": st, "duration_ms": ms, "details": det or {}}
                for at, u, a, st, ms, det in conn.execute(
                    "SELECT at, user_email, action, status, duration_ms, details FROM usage_event "
                    "WHERE action <> 'open_app' ORDER BY at DESC LIMIT 100"
                ).fetchall()
            ]
        if _table_exists(conn, "migration_project"):
            p = conn.execute("SELECT COUNT(*), MIN(created_at), MAX(updated_at) FROM migration_project").fetchone()
            stages = dict(conn.execute("SELECT stage, COUNT(*) FROM project_workflow GROUP BY stage").fetchall())
            out["projects"] = {
                "projects": p[0],
                "first": _iso(p[1]),
                "last": _iso(p[2]),
                "workflows": sum(stages.values()),
                "by_stage": stages,
            }
        if _table_exists(conn, "conversion_history"):
            h = conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT workflow_name), MIN(created_at), MAX(created_at), "
                "AVG(coverage_percentage) FROM conversion_history"
            ).fetchone()
            out["history"] = {
                "conversions": h[0],
                "workflows": h[1],
                "first": _iso(h[2]),
                "last": _iso(h[3]),
                "mean_coverage": round(float(h[4]), 1) if h[4] is not None else None,
                "by_format": dict(
                    conn.execute(
                        "SELECT output_format, COUNT(*) FROM conversion_history GROUP BY 1 ORDER BY 2 DESC"
                    ).fetchall()
                ),
                "by_month": [
                    {"month": str(m), "conversions": n, "workflows": w}
                    for m, n, w in conn.execute(
                        "SELECT to_char(date_trunc('month', created_at), 'YYYY-MM'), COUNT(*), "
                        "COUNT(DISTINCT workflow_name) FROM conversion_history GROUP BY 1 ORDER BY 1"
                    ).fetchall()
                ],
                "recent": [
                    {"at": _iso(at), "workflow": w, "format": f, "coverage": c}
                    for at, w, f, c in conn.execute(
                        "SELECT created_at, workflow_name, output_format, coverage_percentage "
                        "FROM conversion_history ORDER BY created_at DESC LIMIT 50"
                    ).fetchall()
                ],
            }
    return out
