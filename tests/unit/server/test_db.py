"""Database backend detection for the server's one connection pool.

Regression guard: startup once gated the database on ``database_url`` alone, so
the Lakebase path (driven by A2D_LAKEBASE_ENDPOINT + PGHOST, which never sets
database_url) was unreachable by construction.
"""

from __future__ import annotations

from types import SimpleNamespace

from server.services import db


def _settings(**kw):
    base = {"db_backend": "", "lakebase_endpoint": "", "pg_host": "", "database_url": ""}
    base.update(kw)
    return SimpleNamespace(**base)


def test_explicit_backend_wins():
    assert db._resolve_backend(_settings(db_backend="lakebase")) == "lakebase"


def test_lakebase_detected_without_database_url():
    s = _settings(lakebase_endpoint="projects/p/branches/b/endpoints/e", pg_host="h")
    assert db._resolve_backend(s) == "lakebase"


def test_plain_postgres_detected():
    assert db._resolve_backend(_settings(database_url="postgres://x")) == "postgres"


def test_nothing_configured_is_empty():
    assert db._resolve_backend(_settings()) == ""


def test_partial_lakebase_config_is_not_enough():
    """An endpoint without a host can't connect, so don't claim it's configured."""
    assert db._resolve_backend(_settings(lakebase_endpoint="projects/p")) == ""


def test_no_pool_without_a_backend(monkeypatch):
    monkeypatch.setattr(db, "_pool", None)
    monkeypatch.setattr(db, "_resolve_backend", lambda _s: "")
    assert db.get_pool() is None
