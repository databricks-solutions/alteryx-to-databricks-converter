"""Health and stats endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from a2d.__about__ import __version__
from a2d.converters.registry import ConverterRegistry
from server.models.responses import HealthResponse, ReadinessResponse, StatsResponse
from server.services.tool_matrix import get_stats

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(version=__version__)


@router.get("/ready", response_model=ReadinessResponse)
async def ready() -> JSONResponse:
    loaded = len(ConverterRegistry.supported_tools())
    is_ready = loaded > 0
    data = ReadinessResponse(ready=is_ready, converters_loaded=loaded)
    return JSONResponse(
        content=data.model_dump(),
        status_code=200 if is_ready else 503,
    )


@router.get("/stats", response_model=StatsResponse)
async def stats() -> StatsResponse:
    s = get_stats()
    return StatsResponse(version=__version__, **s)
