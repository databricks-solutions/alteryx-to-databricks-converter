"""Migration-readiness questionnaire endpoints.

Read-only and deterministic: serve the question bank, score a set of answers, and
optionally pre-answer the estate questions from an uploaded workflow set. Mirrors
the ``a2d readiness`` CLI. Nothing is persisted; no language model is involved.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, File, HTTPException, UploadFile

from server.services.readiness import get_questions, prefill_answers, score_answers
from server.utils.deadline import run_with_timeout
from server.utils.validation import validate_and_read_files

logger = logging.getLogger("a2d.server.routers.readiness")

router = APIRouter(prefix="/api", tags=["readiness"])


@router.get("/readiness/questions")
async def readiness_questions() -> dict:
    """The question bank (grouped by dimension) plus config defaults for the form."""
    return get_questions()


@router.post("/readiness/score")
async def readiness_score(payload: dict = Body(...)) -> dict:
    """Score a completed (or partial) questionnaire.

    Body: ``{"answers": {question_id: option_value}, "config": {...optional...}}``.
    Unknown question ids or invalid option values answer 422.
    """
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise HTTPException(status_code=400, detail="'answers' must be an object of question_id -> value")
    config = payload.get("config")
    if config is not None and not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="'config' must be an object")

    try:
        return score_answers(answers, config)
    except ValueError as e:
        logger.warning("Validation error scoring readiness answers: %s", e)
        raise HTTPException(status_code=422, detail=str(e)) from None
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error scoring readiness answers")
        raise HTTPException(status_code=500, detail="Internal readiness error") from None


@router.post("/readiness/prefill")
async def readiness_prefill(files: list[UploadFile] = File(...)) -> dict:
    """Suggest estate answers from an uploaded workflow set (the 'smart' prefill)."""
    file_data = await validate_and_read_files(files)

    logger.info("Readiness prefill over %d workflow(s)", len(file_data))
    try:
        return await run_with_timeout(
            prefill_answers,
            file_data,
            label=f"Readiness prefill of {len(file_data)} workflow(s)",
        )
    except ValueError as e:
        logger.warning("Validation error in readiness prefill: %s", e)
        raise HTTPException(status_code=422, detail=str(e)) from None
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error in readiness prefill")
        raise HTTPException(status_code=500, detail="Internal readiness error") from None
