"""Lakebase Autoscale connection pool with OAuth token rotation."""

from __future__ import annotations

import logging

import psycopg
from psycopg_pool import ConnectionPool

logger = logging.getLogger("a2d.server.services.lakebase")


class OAuthConnection(psycopg.Connection):
    """psycopg Connection subclass that injects a fresh Lakebase OAuth token on each connect."""

    _endpoint_name: str = ""

    @classmethod
    def connect(cls, conninfo="", **kwargs):  # type: ignore[override]
        from databricks.sdk import WorkspaceClient

        w = WorkspaceClient()
        cred = w.postgres.generate_database_credential(endpoint=cls._endpoint_name)
        kwargs["password"] = cred.token
        return super().connect(conninfo, **kwargs)


def create_lakebase_pool(
    endpoint_name: str,
    host: str,
    port: int,
    database: str,
    user: str,
    sslmode: str,
    min_size: int = 1,
    max_size: int = 5,
) -> ConnectionPool:
    """Create a connection pool that auto-rotates Lakebase OAuth tokens."""
    OAuthConnection._endpoint_name = endpoint_name
    conninfo = f"dbname={database} user={user} host={host} port={port} sslmode={sslmode}"
    logger.info("Creating Lakebase connection pool (host=%s, db=%s)", host, database)
    return ConnectionPool(
        conninfo=conninfo,
        connection_class=OAuthConnection,
        min_size=min_size,
        max_size=max_size,
        open=True,
    )
