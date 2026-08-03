"""Interactive review workspace endpoint."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from server.services.review import build_review
from server.utils.validation import read_upload, validate_yxmd_file

logger = logging.getLogger("a2d.server.routers.review")

router = APIRouter(prefix="/api", tags=["review"])


@router.post("/review")
async def review(
    file: UploadFile = File(...),
    output_format: str = Form("pyspark"),
) -> dict:
    """Return a per-node review session (canvas + generated code) for one file.

    Powers the interactive review workspace: each node carries its generated
    code, conversion status (auto_accepted / needs_review / cannot_convert),
    confidence and warnings, plus the canvas edges — so the UI can render the
    Alteryx canvas beside the code and drive per-node accept/edit. Reviewer
    decisions are applied client-side against this model.
    """
    validate_yxmd_file(file)
    content = await read_upload(file)

    try:
        result = await asyncio.to_thread(build_review, file.filename or "upload.yxmd", content, output_format)
    except ValueError as e:
        logger.warning("Validation error building review: %s", e)
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        logger.exception("Unexpected error building review session")
        raise HTTPException(status_code=500, detail="Internal review error")

    return result
