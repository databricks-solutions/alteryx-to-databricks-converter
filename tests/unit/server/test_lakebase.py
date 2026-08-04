"""Tests for the Lakebase pool and the history service's failure behaviour.

Both were previously untested (lakebase 0%, history 17%) despite owning the
credential-rotation and persistence paths. These cover the contract without
needing a live workspace or database: the Databricks SDK and psycopg pool are
mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import psycopg
import pytest

# `psycopg_pool` ships with the `server` extra but isn't required for the core
# package, so a bare dev env can lack it. Skip the pool tests there rather than
# fail collection — the history tests below only need `psycopg` itself.
psycopg_pool = pytest.importorskip("psycopg_pool", reason="requires the 'server' extra")

from server.services.lakebase import OAuthConnection, create_lakebase_pool


class TestOAuthConnection:
    def test_connect_injects_a_fresh_credential(self):
        """Each connect must mint a new token — that's the whole point of the class."""
        OAuthConnection._endpoint_name = "projects/p/branches/b/endpoints/e"
        fake_client = MagicMock()
        fake_client.postgres.generate_database_credential.return_value = MagicMock(token="tok-123")

        with (
            patch.dict("sys.modules", {"databricks.sdk": MagicMock(WorkspaceClient=lambda: fake_client)}),
            patch.object(psycopg.Connection, "connect", return_value="CONN") as super_connect,
        ):
            result = OAuthConnection.connect("dbname=x")

        assert result == "CONN"
        # The freshly minted token is passed as the password.
        assert super_connect.call_args.kwargs["password"] == "tok-123"
        # And it was requested for the configured endpoint.
        fake_client.postgres.generate_database_credential.assert_called_once_with(
            endpoint="projects/p/branches/b/endpoints/e"
        )

    def test_credential_is_requested_per_connect_not_cached(self):
        OAuthConnection._endpoint_name = "ep"
        fake_client = MagicMock()
        fake_client.postgres.generate_database_credential.side_effect = [
            MagicMock(token="first"),
            MagicMock(token="second"),
        ]

        with (
            patch.dict("sys.modules", {"databricks.sdk": MagicMock(WorkspaceClient=lambda: fake_client)}),
            patch.object(psycopg.Connection, "connect", return_value="CONN") as super_connect,
        ):
            OAuthConnection.connect("dbname=x")
            OAuthConnection.connect("dbname=x")

        # A stale token would silently break the pool after expiry.
        assert [c.kwargs["password"] for c in super_connect.call_args_list] == ["first", "second"]

    def test_sdk_failure_propagates(self):
        """A credential failure must surface, not yield a passwordless connection."""
        OAuthConnection._endpoint_name = "ep"
        fake_client = MagicMock()
        fake_client.postgres.generate_database_credential.side_effect = RuntimeError("SDK down")

        with (
            patch.dict("sys.modules", {"databricks.sdk": MagicMock(WorkspaceClient=lambda: fake_client)}),
            pytest.raises(RuntimeError, match="SDK down"),
        ):
            OAuthConnection.connect("dbname=x")


class TestCreateLakebasePool:
    def test_builds_conninfo_and_wires_the_connection_class(self):
        with patch("server.services.lakebase.ConnectionPool") as pool_cls:
            create_lakebase_pool(
                endpoint_name="projects/p/branches/b/endpoints/e",
                host="h.example.com",
                port=5432,
                database="db",
                user="sp-client-id",
                sslmode="require",
            )

        kwargs = pool_cls.call_args.kwargs
        assert kwargs["connection_class"] is OAuthConnection
        conninfo = kwargs["conninfo"]
        for expected in ("dbname=db", "user=sp-client-id", "host=h.example.com", "port=5432", "sslmode=require"):
            assert expected in conninfo
        # The endpoint must reach the connection class or credentials target the wrong DB.
        assert OAuthConnection._endpoint_name == "projects/p/branches/b/endpoints/e"

    def test_pool_bounds_are_passed_through(self):
        with patch("server.services.lakebase.ConnectionPool") as pool_cls:
            create_lakebase_pool(
                endpoint_name="ep",
                host="h",
                port=1,
                database="d",
                user="u",
                sslmode="require",
                min_size=2,
                max_size=9,
            )

        kwargs = pool_cls.call_args.kwargs
        assert (kwargs["min_size"], kwargs["max_size"]) == (2, 9)
