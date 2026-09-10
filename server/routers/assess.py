"""Migration-profiler endpoint."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from a2d.analyzer.profiler import (
    DEFAULT_CATEGORY_TIERS,
    DEFAULT_HOUR_ANCHORS,
    TIER_ORDER,
)
from server.services.assess import profile_estate
from server.utils.deadline import run_with_timeout
from server.utils.validation import validate_and_read_files

logger = logging.getLogger("a2d.server.routers.assess")

router = APIRouter(prefix="/api", tags=["assess"])


@router.get("/assess/config-defaults")
async def assess_config_defaults() -> dict:
    """Default profiler config for the App settings panel to render from."""
    return {
        "tiers": list(TIER_ORDER),
        "category_tiers": dict(DEFAULT_CATEGORY_TIERS),
        "hour_anchors": dict(DEFAULT_HOUR_ANCHORS),
    }


@router.post("/assess")
async def assess(
    files: list[UploadFile] = File(...),
    hours: bool = Form(False),
    config: str | None = Form(None),
) -> dict:
    """Profile an estate: totals, size distribution, difficulty, tool-difficulty tiers.

    ``hours`` opts into the model-based effort estimate (off by default). ``config``
    is an optional JSON string of profiler-config overrides (``category_tiers``,
    ``tool_overrides``, ``hour_anchors``, ...) merged over the defaults.
    """
    file_data = await validate_and_read_files(files)

    overrides: dict | None = None
    if config:
        try:
            parsed = json.loads(config)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid config JSON: {e}")
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="config must be a JSON object")
        overrides = parsed

    logger.info("Profiling %d workflow(s) (hours=%s, custom_config=%s)", len(file_data), hours, overrides is not None)
    try:
        result = await run_with_timeout(
            lambda fd: profile_estate(fd, show_hours=hours, overrides=overrides),
            file_data,
            label=f"Profiling {len(file_data)} workflow(s)",
        )
    except ValueError as e:
        logger.warning("Validation error profiling files: %s", e)
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error profiling files")
        raise HTTPException(status_code=500, detail="Internal profiler error")

    return result
