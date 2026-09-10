"""Migration-profiler endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from server.services.assess import profile_estate
from server.utils.deadline import run_with_timeout
from server.utils.validation import validate_and_read_files

logger = logging.getLogger("a2d.server.routers.assess")

router = APIRouter(prefix="/api", tags=["assess"])


@router.post("/assess")
async def assess(
    files: list[UploadFile] = File(...),
    hours: bool = Form(False),
) -> dict:
    """Profile an estate: totals, size distribution, difficulty, tool-difficulty tiers.

    ``hours`` opts into the model-based effort estimate (off by default).
    """
    file_data = await validate_and_read_files(files)

    logger.info("Profiling %d workflow(s) (hours=%s)", len(file_data), hours)
    try:
        result = await run_with_timeout(
            lambda fd: profile_estate(fd, show_hours=hours),
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
