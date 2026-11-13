"""The server's one PostgreSQL / Lakebase connection pool.

The database is optional. With none configured, :func:`get_pool` returns None and
the app runs session-only projects in the browser. The migration-project store
(:mod:`server.services.project`) is the only user of the pool.

psycopg comes with the ``server`` extra, and this module must stay importable
without it (the rest of the server, and the CLI, don't need a database), so the
import is tolerant. With no driver installed there is no pool either, and the
guarded blocks are unreachable.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("a2d.server.services.db")

try:
    from psycopg import Error as DatabaseError
except ModuleNotFoundError:  # pragma: no cover - only when the extra is absent

    class DatabaseError(Exception):  # type: ignore[no-redef]
        """Placeholder so `except` clauses stay valid without psycopg."""


_pool = None


def _resolve_backend(settings) -> str:
    """Determine the database backend from settings (auto-detect if not explicit)."""
    if settings.db_backend:
        return settings.db_backend
    if settings.lakebase_endpoint and settings.pg_host:
        return "lakebase"
    if settings.database_url:
        return "postgres"
    return ""


def resolve_backend() -> str:
    """Return the configured backend name, or "" when no database is configured.

    Checking a single setting instead (e.g. ``database_url``) would miss the
    Lakebase path, which is driven by ``A2D_LAKEBASE_ENDPOINT`` + ``PGHOST``.
    """
    from server.settings import settings

    return _resolve_backend(settings)


def get_pool():
    """Return the connection pool, or None if no database is configured (or the
    pool couldn't be created)."""
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


def close_pool() -> None:
    """Close and forget the pool (shutdown, and tests that swap databases)."""
    global _pool
    if _pool is not None:
        try:
            _pool.close()
        finally:
            _pool = None
