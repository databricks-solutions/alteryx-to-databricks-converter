"""FastAPI application — serves API + React static build."""

from __future__ import annotations

import asyncio
import functools
import logging
import re
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from a2d.__about__ import __version__
from server.routers import (
    ai,
    analyze,
    assess,
    convert,
    health,
    insights,
    projects,
    readiness,
    review,
    tools,
    usage,
    validate,
)
from server.services import db
from server.services import project as project_service
from server.services import usage as usage_service
from server.services.batch import get_store
from server.settings import settings
from server.utils.identity import current_user
from server.websocket import batch as ws_batch

logger = logging.getLogger("a2d.server")


async def _evict_expired_jobs() -> None:
    """Periodically remove expired batch jobs."""
    while True:
        try:
            await asyncio.sleep(300)  # every 5 minutes
            count = get_store().evict_expired()
            if count:
                logger.info("Evicted %d expired batch jobs", count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error during job eviction")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Configure logging from settings
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Startup: ensure converters are loaded
    import a2d.converters  # noqa: F401

    # The database is optional: it backs saved migration projects. Ask which
    # backend is configured rather than checking `database_url` directly: the
    # Lakebase path is driven by A2D_LAKEBASE_ENDPOINT + PGHOST and never sets
    # `database_url`.
    backend = db.resolve_backend()
    if backend:
        if project_service.init_db():
            logger.info("Migration-project store ready (backend=%s)", backend)
        if settings.usage_tracking or settings.db_readers:
            usage_service.init_db()
        else:
            # Retried lazily on the next project request (see project.is_available).
            logger.warning("Migration-project store configured (backend=%s) but failed to initialize", backend)
    else:
        logger.info("No database configured: saved projects are off, the app keeps projects in the browser")

    logger.info("a2d API v%s starting up", __version__)
    cleanup_task = asyncio.create_task(_evict_expired_jobs())
    yield
    cleanup_task.cancel()
    with suppress(asyncio.CancelledError):
        await cleanup_task
    db.close_pool()
    logger.info("a2d API shutting down")


app = FastAPI(
    title="a2d API",
    description="Alteryx-to-Databricks Migration Accelerator API",
    version=__version__,
    lifespan=lifespan,
)

# CORS from settings.
#
# In Databricks Apps the SPA is served by THIS app (see the static mount below),
# so requests are same-origin and need no CORS at all. These settings exist for
# local development, where Vite runs on a different port.
#
# `allow_credentials=True` with a wildcard origin is invalid per the CORS spec
# (browsers reject `Access-Control-Allow-Origin: *` on a credentialed request),
# and asking for it would silently break those requests while widening exposure.
# So credentials are only enabled for an explicit origin allowlist.
_wildcard_origin = "*" in settings.cors_origins
if _wildcard_origin:
    logger.warning(
        "A2D_CORS_ORIGINS is '*' — credentialed cross-origin requests are disabled. "
        "Set an explicit origin allowlist if you need them."
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=not _wildcard_origin,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)


# ── usage ──────────────────────────────────────────────────────────────────
# Which requests are recorded (method, path, action). A page load of the app
# itself is "open_app"; client-side navigation within it isn't a request.
_TRACKED = [
    (method, re.compile(pattern), action)
    for method, pattern, action in (
        ("POST", r"^/api/convert$", "convert"),
        ("POST", r"^/api/convert/batch$", "convert_batch"),
        ("POST", r"^/api/analyze$", "analyze"),
        ("POST", r"^/api/assess$", "assess"),
        ("POST", r"^/api/review$", "review"),
        ("POST", r"^/api/advise$", "advise"),
        ("POST", r"^/api/savings$", "business_case"),
        ("POST", r"^/api/portfolio$", "portfolio"),
        ("POST", r"^/api/readiness/score$", "readiness"),
        ("POST", r"^/api/validate$", "syntax_check"),
        ("POST", r"^/api/ai/complete$", "ai_complete"),
        ("POST", r"^/api/ai/suggest$", "ai_suggest"),
        ("POST", r"^/api/ai/feedback$", "ai_feedback"),
        ("POST", r"^/api/projects$", "project_create"),
        ("POST", r"^/api/projects/(?P<project>[^/]+)/workflows$", "workflows_add"),
        ("DELETE", r"^/api/projects/(?P<project>[^/]+)/workflows/[^/]+$", "workflow_remove"),
        ("DELETE", r"^/api/projects/(?P<project>[^/]+)$", "project_delete"),
        ("GET", r"^/(?!api/|assets/|ws/)[^.]*$", "open_app"),
    )
]


def _tracked(method: str, path: str) -> tuple[str | None, str | None]:
    for m, pattern, action in _TRACKED:
        if m == method:
            match = pattern.match(path)
            if match:
                return action, match.groupdict().get("project")
    return None, None


@app.middleware("http")
async def _record_usage(request: Request, call_next):
    """Record tracked requests after they finish (see server.services.usage)."""
    action, project = _tracked(request.method, request.url.path)
    if action is None or not settings.usage_tracking:
        return await call_next(request)
    started = time.monotonic()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        details = dict(getattr(request.state, "usage", None) or {})
        record = functools.partial(
            usage_service.record,
            action,
            user=current_user(request),
            status=status,
            duration_ms=int((time.monotonic() - started) * 1000),
            project_id=details.pop("project_id", None) or project or request.query_params.get("project_id"),
            details=details,
        )
        # Off the request path: a slow or broken database must not slow the app.
        asyncio.get_running_loop().run_in_executor(None, record)


@app.exception_handler(project_service.StoreUnavailableError)
async def store_unavailable_handler(request: Request, exc: project_service.StoreUnavailableError) -> JSONResponse:
    # A configured database that isn't responding: say so (503), so the client
    # doesn't read an outage as "this project was deleted" or "no projects".
    logger.warning("Project store unavailable on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "status_code": 500},
    )


# API routers
app.include_router(health.router)
app.include_router(tools.router)
app.include_router(convert.router)
app.include_router(analyze.router)
app.include_router(assess.router)
app.include_router(validate.router)
app.include_router(review.router)
app.include_router(insights.router)
app.include_router(readiness.router)
app.include_router(projects.router)
app.include_router(ai.router)
app.include_router(usage.router)

# WebSocket
app.include_router(ws_batch.router)

# Serve React build in production (after API routes so /api/* takes priority)
_frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    _assets_dir = _frontend_dist / "assets"
    if _assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    _index_html = _frontend_dist / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # Don't swallow unknown API/WebSocket paths with HTML — let them 404 as JSON.
        if full_path in {"api", "ws"} or full_path.startswith(("api/", "ws/")):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        # Real static file at root (favicon, theme-init.js, robots.txt, ...)
        if full_path:
            candidate = _frontend_dist / full_path
            if candidate.is_file() and _frontend_dist in candidate.resolve().parents:
                return FileResponse(candidate)
        # Otherwise hand off to the SPA so client-side routing can handle the path
        return FileResponse(_index_html)
else:
    logger.warning("frontend/dist not found — web UI disabled. Run 'make frontend' to build it.")
