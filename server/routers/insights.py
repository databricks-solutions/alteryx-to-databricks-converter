"""Estate-level insight endpoints: portfolio analysis and cluster/cost advice.

Both features existed only as CLI commands (`a2d portfolio`, `a2d advise`) despite
being the most stakeholder-facing outputs the tool produces — the people who want
an estate migration plan or a cluster recommendation are the least likely to open a
terminal. These endpoints put them behind the web UI too.

Both are deterministic and read-only: they analyze uploads in a temp directory and
return JSON. Nothing is persisted.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from server.services.advise import advise_workflow
from server.services.portfolio import analyze_portfolio
from server.utils.deadline import run_with_timeout
from server.utils.validation import read_upload, validate_and_read_files, validate_yxmd_file

logger = logging.getLogger("a2d.server.routers.insights")

router = APIRouter(prefix="/api", tags=["insights"])


@router.post("/portfolio")
async def portfolio(files: list[UploadFile] = File(...)) -> dict:
    """Analyze a whole estate: dependencies, shared macros, duplicates, waves.

    Takes several workflows at once — the value is entirely in the cross-workflow
    view (which workflow feeds which, what's duplicated, what order to migrate in),
    so a single file yields a thin but valid report.
    """
    file_data = await validate_and_read_files(files)

    logger.info("Portfolio analysis over %d workflow(s)", len(file_data))
    try:
        return await run_with_timeout(
            analyze_portfolio, file_data, label=f"Portfolio analysis of {len(file_data)} workflow(s)"
        )
    except ValueError as e:
        logger.warning("Validation error in portfolio analysis: %s", e)
        raise HTTPException(status_code=422, detail=str(e)) from None
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error in portfolio analysis")
        raise HTTPException(status_code=500, detail="Internal portfolio error") from None


@router.post("/advise")
async def advise(
    file: UploadFile = File(...),
    cloud: str = Form("aws"),
) -> dict:
    """Recommend a cluster size and surface Spark optimization hints."""
    validate_yxmd_file(file)
    content = await read_upload(file)

    logger.info("Advisory for %s (cloud=%s)", file.filename, cloud)
    try:
        return await run_with_timeout(
            advise_workflow,
            file.filename or "upload.yxmd",
            content,
            cloud,
            label=f"Advisory for {file.filename}",
        )
    except ValueError as e:
        logger.warning("Validation error in advisory: %s", e)
        raise HTTPException(status_code=422, detail=str(e)) from None
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error in advisory")
        raise HTTPException(status_code=500, detail="Internal advisory error") from None
