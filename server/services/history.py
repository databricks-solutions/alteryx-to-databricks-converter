"""History service — persist conversion results to PostgreSQL/Lakebase."""

from __future__ import annotations

import json
import logging
import uuid

logger = logging.getLogger("a2d.server.services.history")

_pool = None
_initialized = False

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS conversion_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_name TEXT NOT NULL,
    output_format TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    node_count INT NOT NULL,
    edge_count INT NOT NULL,
    coverage_percentage FLOAT,
    warnings JSONB DEFAULT '[]',
    files JSONB NOT NULL,
    dag_data JSONB,
    stats JSONB
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_history_created ON conversion_history(created_at DESC);
"""


def _resolve_backend(settings) -> str:
    """Determine the database backend from settings (auto-detect if not explicit)."""
    if settings.db_backend:
        return settings.db_backend
    if settings.lakebase_endpoint and settings.pg_host:
        return "lakebase"
    if settings.database_url:
        return "postgres"
    return ""


def _get_pool():
    """Return the connection pool, or None if database is not configured."""
    global _pool
    if _pool is not None:
        return _pool

    from server.settings import settings

    backend = _resolve_backend(settings)
    if not backend:
        return None

    try:
        if backend == "lakebase":
            from server.services.lakebase import create_lakebase_pool

            _pool = create_lakebase_pool(
                endpoint_name=settings.lakebase_endpoint,
                host=settings.pg_host,
                port=settings.pg_port,
                database=settings.pg_database,
                user=settings.pg_user,
                sslmode=settings.pg_sslmode,
            )
        else:
            from psycopg_pool import ConnectionPool

            _pool = ConnectionPool(settings.database_url, min_size=1, max_size=5)
        return _pool
    except Exception:
        logger.exception("Failed to create database connection pool (backend=%s)", backend)
        return None


def init_db() -> bool:
    """Create tables if they don't exist. Returns True if database is available."""
    global _initialized
    pool = _get_pool()
    if pool is None:
        return False

    try:
        with pool.connection() as conn:
            conn.execute(_CREATE_TABLE)
            conn.execute(_CREATE_INDEX)
            conn.commit()
        _initialized = True
        logger.info("History database initialized")
        return True
    except Exception:
        logger.exception("Failed to initialize history database")
        return False


def is_available() -> bool:
    """Check if history feature is available."""
    return _initialized and _get_pool() is not None


def save_conversion(data: dict) -> str | None:
    """Save conversion result to database. Returns UUID or None."""
    pool = _get_pool()
    if pool is None or not _initialized:
        return None

    record_id = str(uuid.uuid4())
    coverage = None
    stats = data.get("stats")
    if isinstance(stats, dict):
        coverage = stats.get("coverage_percentage")

    try:
        with pool.connection() as conn:
            conn.execute(
                """INSERT INTO conversion_history
                   (id, workflow_name, output_format, node_count, edge_count,
                    coverage_percentage, warnings, files, dag_data, stats)
                   VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)""",
                (
                    record_id,
                    data.get("workflow_name", "unknown"),
                    data.get("output_format", "pyspark"),
                    data.get("node_count", 0),
                    data.get("edge_count", 0),
                    coverage,
                    json.dumps(data.get("warnings", [])),
                    json.dumps(data.get("files", [])),
                    json.dumps(data.get("dag_data")),
                    json.dumps(data.get("stats")),
                ),
            )
            conn.commit()
        return record_id
    except Exception:
        logger.exception("Failed to save conversion to history")
        return None


def list_conversions(limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    """List conversions (summary only, no files/dag_data). Returns (items, total)."""
    pool = _get_pool()
    if pool is None or not _initialized:
        return [], 0

    try:
        with pool.connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM conversion_history").fetchone()
            total = row[0] if row else 0

            rows = conn.execute(
                """SELECT id, workflow_name, output_format, created_at,
                          node_count, edge_count, coverage_percentage
                   FROM conversion_history
                   ORDER BY created_at DESC
                   LIMIT %s OFFSET %s""",
                (limit, offset),
            ).fetchall()

        items = [
            {
                "id": str(r[0]),
                "workflow_name": r[1],
                "output_format": r[2],
                "created_at": r[3].isoformat() if r[3] else "",
                "node_count": r[4],
                "edge_count": r[5],
                "coverage_percentage": r[6],
            }
            for r in rows
        ]
        return items, total
    except Exception:
        logger.exception("Failed to list conversions")
        return [], 0


def get_conversion(record_id: str) -> dict | None:
    """Get full conversion record by ID."""
    pool = _get_pool()
    if pool is None or not _initialized:
        return None

    try:
        with pool.connection() as conn:
            row = conn.execute(
                """SELECT id, workflow_name, output_format, created_at,
                          node_count, edge_count, coverage_percentage,
                          warnings, files, dag_data, stats
                   FROM conversion_history WHERE id = %s""",
                (record_id,),
            ).fetchone()

        if not row:
            return None

        return {
            "id": str(row[0]),
            "workflow_name": row[1],
            "output_format": row[2],
            "created_at": row[3].isoformat() if row[3] else "",
            "node_count": row[4],
            "edge_count": row[5],
            "coverage_percentage": row[6],
            "warnings": row[7] or [],
            "files": row[8] or [],
            "dag_data": row[9],
            "stats": row[10] or {},
        }
    except Exception:
        logger.exception("Failed to get conversion %s", record_id)
        return None


def delete_conversion(record_id: str) -> bool:
    """Delete a conversion record. Returns True if deleted."""
    pool = _get_pool()
    if pool is None or not _initialized:
        return False

    try:
        with pool.connection() as conn:
            result = conn.execute(
                "DELETE FROM conversion_history WHERE id = %s",
                (record_id,),
            )
            conn.commit()
            return (result.rowcount or 0) > 0
    except Exception:
        logger.exception("Failed to delete conversion %s", record_id)
        return False
