"""Application settings loaded from environment variables.

Lakebase / Postgres connection fields prefer the *native* PG environment
variables (``PGHOST``, ``PGPORT``, ``PGDATABASE``, ``PGUSER``, ``PGSSLMODE``)
that the Databricks Apps runtime auto-injects when a ``database`` resource is
bound to the app. The legacy ``A2D_PG_*`` names are preserved as fallbacks so
existing deployments continue to work without code changes.

Resolution order per field (first non-empty value wins):

1. Native PG var (e.g. ``PGHOST``)
2. Legacy a2d-prefixed var (e.g. ``A2D_PG_HOST``)
3. Hard-coded default declared on the field

The ``lakebase_endpoint`` field is intentionally a2d-specific because the
endpoint name is not auto-injected by the App runtime — it must come from the
deploy-time ``lakebase_endpoint`` variable in ``databricks.yml``.
"""

from __future__ import annotations

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings

_VALID_LOG_LEVELS = {"debug", "info", "warning", "error", "critical"}


class Settings(BaseSettings):
    # NOTE: ``populate_by_name=True`` lets us define a Python field name (``pg_host``)
    # while accepting *either* the native ``PGHOST`` env var or the legacy
    # ``A2D_PG_HOST`` env var via ``AliasChoices``. The class-level ``env_prefix``
    # still applies to fields that don't declare an explicit ``validation_alias``.
    model_config = {"env_prefix": "A2D_", "populate_by_name": True}

    # CORS
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    cors_allow_methods: list[str] = ["GET", "POST", "OPTIONS"]
    cors_allow_headers: list[str] = ["Content-Type", "Authorization"]

    # Upload limits
    max_upload_size_bytes: int = 50 * 1024 * 1024  # 50 MB
    max_batch_files: int = 50
    allowed_extensions: set[str] = {".yxmd"}

    # Job management
    job_ttl_seconds: int = 3600  # 1 hour

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"

    # Database (optional — history disabled when empty)
    database_url: str = ""

    # Lakebase (optional — only used when db_backend == "lakebase")
    db_backend: str = ""  # "" (auto-detect), "postgres", or "lakebase"
    lakebase_endpoint: str = ""  # projects/<id>/branches/<id>/endpoints/<id>

    # Postgres connection params — read PG* first (native, auto-injected by
    # the Databricks Apps database binding) then fall back to A2D_PG_* aliases.
    pg_host: str = Field(
        default="",
        validation_alias=AliasChoices("PGHOST", "A2D_PG_HOST"),
    )
    pg_port: int = Field(
        default=5432,
        validation_alias=AliasChoices("PGPORT", "A2D_PG_PORT"),
    )
    pg_database: str = Field(
        default="databricks_postgres",
        validation_alias=AliasChoices("PGDATABASE", "A2D_PG_DATABASE"),
    )
    # For Lakebase Autoscaling on Databricks Apps, the Postgres role name is
    # the App SP's client_id. The Apps runtime injects DATABRICKS_CLIENT_ID
    # into the App container, so we use it as the final fallback after the
    # explicit env vars. Order: PGUSER > A2D_PG_USER > DATABRICKS_CLIENT_ID
    # (Apps auto-injection) > "" (history disabled).
    pg_user: str = Field(
        default="",
        validation_alias=AliasChoices("PGUSER", "A2D_PG_USER", "DATABRICKS_CLIENT_ID"),
    )
    pg_sslmode: str = Field(
        default="require",
        validation_alias=AliasChoices("PGSSLMODE", "A2D_PG_SSLMODE"),
    )

    @field_validator("max_upload_size_bytes")
    @classmethod
    def _positive_upload_size(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("max_upload_size_bytes must be positive")
        return v

    @field_validator("max_batch_files")
    @classmethod
    def _positive_batch_files(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("max_batch_files must be positive")
        return v

    @field_validator("job_ttl_seconds")
    @classmethod
    def _positive_ttl(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("job_ttl_seconds must be positive")
        return v

    @field_validator("db_backend")
    @classmethod
    def _valid_db_backend(cls, v: str) -> str:
        allowed = {"", "postgres", "lakebase"}
        if v not in allowed:
            raise ValueError(f"db_backend must be one of {allowed}")
        return v

    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, v: str) -> str:
        if v.lower() not in _VALID_LOG_LEVELS:
            raise ValueError(f"log_level must be one of {_VALID_LOG_LEVELS}")
        return v.lower()


settings = Settings()
