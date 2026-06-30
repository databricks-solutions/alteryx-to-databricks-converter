"""Analysis endpoint."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from server.models.responses import AnalysisResponse
from server.services.analysis import analyze_files
from server.utils.validation import validate_and_read_files

logger = logging.getLogger("a2d.server.routers.analyze")

router = APIRouter(prefix="/api", tags=["analyze"])


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze(
    files: list[UploadFile] = File(...),
) -> AnalysisResponse:
    file_data = await validate_and_read_files(files)

    logger.info("Analyzing %d workflow(s)", len(file_data))
    try:
        result = await asyncio.to_thread(analyze_files, file_data)
    except ValueError as e:
        logger.warning("Validation error analyzing files: %s", e)
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        logger.exception("Unexpected error analyzing files")
        raise HTTPException(status_code=500, detail="Internal analysis error")

    logger.info("Analysis complete: %d workflows", len(file_data))
    return AnalysisResponse(**result)
