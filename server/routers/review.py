"""Interactive review workspace endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from server.services.review import build_review
from server.utils.deadline import run_with_timeout
from server.utils.project_input import resolve_one_workflow

logger = logging.getLogger("a2d.server.routers.review")

router = APIRouter(prefix="/api", tags=["review"])


@router.post("/review")
async def review(
    file: UploadFile | None = File(None),
    project_id: str | None = Form(None),
    workflow_id: str | None = Form(None),
    macros: list[UploadFile] = File(default=[]),
    output_format: str = Form("pyspark"),
) -> dict:
    """Return a per-node review session (canvas + generated code) for one file.

    Powers the interactive review workspace: each node carries its generated
    code, conversion status (auto_accepted / needs_review / cannot_convert),
    confidence and warnings, plus the canvas edges — so the UI can render the
    Alteryx canvas beside the code and drive per-node accept/edit. Reviewer
    decisions are applied client-side against this model. The workflow is an
    upload (``file``, plus ``macros``) or a saved project's (``project_id`` +
    ``workflow_id``), the same as ``/api/convert``.
    """
    wf = await resolve_one_workflow(file, project_id, workflow_id, macros)

    try:
        result = await run_with_timeout(
            build_review,
            wf.name,
            wf.content,
            output_format,
            wf.macros,
            label=f"Building review for {wf.name}",
        )
    except ValueError as e:
        logger.warning("Validation error building review: %s", e)
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error building review session")
        raise HTTPException(status_code=500, detail="Internal review error")

    return result
