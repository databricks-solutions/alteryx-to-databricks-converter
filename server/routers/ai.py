"""AI completion endpoints: the only routes that return model-written content.

Each takes one workflow, either uploaded or from a saved project
(``project_id`` + ``workflow_id``), and the same conversion options as Convert:

* ``POST /api/ai/gaps``: what the deterministic converter couldn't finish, and
  which steps AI completion would work on. No model call, so it works without AI.
* ``POST /api/ai/complete``: a separate, clearly marked copy of the PySpark
  notebook with only those steps filled in by the model.
* ``POST /api/ai/notes``: the Markdown suggestions notes, as a download.

AI is opt-in: without a configured FMAPI endpoint, ``complete`` and ``notes``
answer 422 with what to set. The deterministic output is never modified.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from lxml.etree import XMLSyntaxError
from starlette.concurrency import run_in_threadpool

from a2d.advisor.completion import CompletionUnavailableError
from a2d.exceptions import A2dError
from server.models.requests import ConversionOptions, conversion_options
from server.services import ai_completion
from server.services import project as project_service
from server.utils.deadline import run_with_timeout
from server.utils.headers import content_disposition
from server.utils.project_input import check_project_id, require_projects
from server.utils.validation import read_upload, validate_yxmd_file

logger = logging.getLogger("a2d.server.routers.ai")

router = APIRouter(prefix="/api/ai", tags=["ai"])

_NOT_CONFIGURED = (
    "AI completion is opt-in and no Foundation Model API endpoint is configured. "
    "Set A2D_FMAPI_ENDPOINT (and A2D_FMAPI_TOKEN if the endpoint needs a token) to "
    "enable it. Conversion itself never requires a model."
)


def _require_client():
    client = ai_completion.get_client()
    if client is None:
        raise HTTPException(status_code=422, detail=_NOT_CONFIGURED)
    return client


async def _one_workflow(file: UploadFile | None, project_id: str | None, workflow_id: str | None) -> tuple[str, bytes]:
    if project_id or workflow_id:
        if file is not None and file.filename:
            raise HTTPException(status_code=422, detail="Send either a file or project_id + workflow_id, not both.")
        if not (project_id and workflow_id):
            raise HTTPException(status_code=422, detail="Pass both project_id and workflow_id.")
        require_projects()
        check_project_id(project_id)
        check_project_id(workflow_id)
        stored = await run_in_threadpool(project_service.get_workflow_file, project_id, workflow_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="Unknown project or workflow.")
        return stored
    if file is None:
        raise HTTPException(status_code=422, detail="Upload a workflow, or pass project_id and workflow_id.")
    validate_yxmd_file(file)
    return file.filename or "upload.yxmd", await read_upload(file)


def _bad_workflow(name: str, exc: Exception) -> HTTPException:
    logger.warning("Could not convert %s for AI: %s", name, exc)
    return HTTPException(status_code=422, detail=f"{name} couldn't be converted: {exc}")


@router.get("/status")
async def ai_status() -> dict:
    """Whether a model endpoint is configured, so the UI can show the opt-in note."""
    return {"enabled": ai_completion.is_enabled()}


@router.post("/gaps")
async def gaps(
    file: UploadFile | None = File(None),
    project_id: str | None = Form(None),
    workflow_id: str | None = Form(None),
    opts: ConversionOptions = Depends(conversion_options),
) -> dict:
    """What the converter couldn't finish for one workflow (no model call)."""
    name, content = await _one_workflow(file, project_id, workflow_id)
    try:
        return await run_with_timeout(ai_completion.gap_summary, name, content, opts, label=f"Checking {name}")
    except (ValueError, XMLSyntaxError, A2dError) as e:
        raise _bad_workflow(name, e) from None


@router.post("/complete")
async def complete(
    file: UploadFile | None = File(None),
    project_id: str | None = Form(None),
    workflow_id: str | None = Form(None),
    opts: ConversionOptions = Depends(conversion_options),
) -> dict:
    """Return an AI-completed copy of the workflow's PySpark notebook."""
    client = _require_client()
    name, content = await _one_workflow(file, project_id, workflow_id)
    try:
        return await run_with_timeout(
            ai_completion.complete_workflow,
            name,
            content,
            client,
            opts,
            label=f"AI completion for {name}",
        )
    except ai_completion.CompletionBusyError as e:
        raise HTTPException(status_code=429, detail=str(e)) from None
    except CompletionUnavailableError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    except (ValueError, XMLSyntaxError, A2dError) as e:
        raise _bad_workflow(name, e) from None


@router.post("/notes", response_class=PlainTextResponse)
async def notes(
    file: UploadFile | None = File(None),
    project_id: str | None = Form(None),
    workflow_id: str | None = Form(None),
    opts: ConversionOptions = Depends(conversion_options),
) -> PlainTextResponse:
    """Return the AI suggestions notes (Markdown) for one workflow, as a download."""
    client = _require_client()
    name, content = await _one_workflow(file, project_id, workflow_id)
    try:
        filename, markdown = await run_with_timeout(
            ai_completion.suggestions_markdown, name, content, client, opts, label=f"Notes for {name}"
        )
    except (ValueError, XMLSyntaxError, A2dError) as e:
        raise _bad_workflow(name, e) from None
    return PlainTextResponse(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": content_disposition(filename)},
    )
