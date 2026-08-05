"""History service failure behaviour.

Previously 17% covered despite owning the persistence path. A database outage
must degrade gracefully (history is optional and the conversion must still
succeed), while a genuine programming error must still surface rather than being
reported to the user as "no history".

These need no database: the pool is mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from server.services import history as history_service


def _pool_raising(exc: Exception):
    pool = MagicMock()
    pool.connection.side_effect = exc
    return pool


@pytest.fixture(autouse=True)
def _mark_initialized(monkeypatch):
    """Every function short-circuits unless the schema was initialized.

    Without this the tests would pass for the wrong reason — returning the
    degraded value from the early guard, never reaching the database call under
    test.
    """
    monkeypatch.setattr(history_service, "_initialized", True)


class TestHistoryDegradesOnDatabaseErrors:
    """A DB outage must not 500 the app — but a real bug must not be hidden."""

    def test_list_returns_empty_on_db_error(self):
        with patch.object(
            history_service, "_get_pool", return_value=_pool_raising(history_service._DatabaseError("down"))
        ):
            assert history_service.list_conversions() == ([], 0)

    def test_get_returns_none_on_db_error(self):
        with patch.object(
            history_service, "_get_pool", return_value=_pool_raising(history_service._DatabaseError("down"))
        ):
            assert history_service.get_conversion("abc") is None

    def test_delete_returns_false_on_db_error(self):
        with patch.object(
            history_service, "_get_pool", return_value=_pool_raising(history_service._DatabaseError("down"))
        ):
            assert history_service.delete_conversion("abc") is False

    def test_save_returns_none_on_db_error(self):
        with patch.object(
            history_service, "_get_pool", return_value=_pool_raising(history_service._DatabaseError("down"))
        ):
            assert history_service.save_conversion({"workflow_name": "wf"}) is None

    @pytest.mark.parametrize(
        "operation",
        [
            lambda: history_service.list_conversions(),
            lambda: history_service.get_conversion("abc"),
            lambda: history_service.delete_conversion("abc"),
        ],
    )
    def test_programming_errors_are_not_swallowed(self, operation):
        """A TypeError/AttributeError is a bug, not a "no history" condition."""
        with (
            patch.object(history_service, "_get_pool", return_value=_pool_raising(TypeError("bug"))),
            pytest.raises(TypeError, match="bug"),
        ):
            operation()


class TestResolveBackend:
    """Startup asks resolve_backend() which backend is configured.

    Regression guard: startup previously gated history on `database_url` alone,
    so the Lakebase path — driven by A2D_LAKEBASE_ENDPOINT + PGHOST, which never
    sets database_url — was unreachable by construction. The app logged
    "not configured" even with a correctly bound Lakebase database.
    """

    def _settings(self, **kw):
        from types import SimpleNamespace

        base = {"db_backend": "", "lakebase_endpoint": "", "pg_host": "", "database_url": ""}
        base.update(kw)
        return SimpleNamespace(**base)

    def test_explicit_backend_wins(self):
        assert history_service._resolve_backend(self._settings(db_backend="lakebase")) == "lakebase"

    def test_lakebase_detected_without_database_url(self):
        """The exact case that was broken: no database_url, but Lakebase configured."""
        s = self._settings(lakebase_endpoint="projects/p/branches/b/endpoints/e", pg_host="h")
        assert history_service._resolve_backend(s) == "lakebase"

    def test_plain_postgres_detected(self):
        assert history_service._resolve_backend(self._settings(database_url="postgres://x")) == "postgres"

    def test_nothing_configured_is_empty(self):
        assert history_service._resolve_backend(self._settings()) == ""

    def test_partial_lakebase_config_is_not_enough(self):
        """Endpoint without a host can't connect, so don't claim it's configured."""
        assert history_service._resolve_backend(self._settings(lakebase_endpoint="projects/p")) == ""
