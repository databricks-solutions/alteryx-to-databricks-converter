"""FastAPI application — serves API + React static build."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from a2d.__about__ import __version__
from server.routers import (
    analyze,
    convert,
    health,
    history,
    tools,
    validate,
)
from server.services import history as history_service
from server.services.batch import get_store
from server.settings import settings
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

    # Initialize history database (optional)
    if settings.database_url:
        if history_service.init_db():
            logger.info("History database connected")
        else:
            logger.warning("History database configured but failed to initialize")
    else:
        logger.info("History database not configured — history feature disabled")

    logger.info("a2d API v%s starting up", __version__)
    cleanup_task = asyncio.create_task(_evict_expired_jobs())
    yield
    cleanup_task.cancel()
    with suppress(asyncio.CancelledError):
        await cleanup_task
    logger.info("a2d API shutting down")


app = FastAPI(
    title="a2d API",
    description="Alteryx-to-Databricks Migration Accelerator API",
    version=__version__,
    lifespan=lifespan,
)

# CORS from settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)


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
app.include_router(history.router)
app.include_router(validate.router)

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
