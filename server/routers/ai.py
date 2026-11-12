"""AI completion endpoints — the only routes that return model-written code.

Each takes one workflow, either uploaded or from a saved project
(``project_id`` + ``workflow_id``), and the same conversion options as Convert:

* ``POST /api/ai/gaps`` — what the deterministic converter couldn't finish. No
  model call, so it works without AI configured.
* ``POST /api/ai/complete`` — a separate, clearly marked copy of the PySpark
  notebook with only those cells filled in by the model.
* ``POST /api/ai/notes`` — the Markdown suggestions notes, as a download.

AI is opt-in: without a configured FMAPI endpoint, ``complete`` and ``notes``
answer 422 with what to set. The deterministic output is never modified.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse

from a2d.advisor.llm_client import LLMRequestError
from server.models.requests import ConversionOptions, conversion_options
from server.services import ai_completion
from server.services import chat as chat_service
from server.services import project as project_service
from server.utils.deadline import run_with_timeout
from server.utils.validation import read_upload, validate_yxmd_file

logger = logging.getLogger("a2d.server.routers.ai")

router = APIRouter(prefix="/api/ai", tags=["ai"])

_NOT_CONFIGURED = (
    "AI completion is opt-in and no Foundation Model API endpoint is configured. "
    "Set A2D_FMAPI_ENDPOINT (and A2D_FMAPI_TOKEN if the endpoint needs a token) to "
    "enable it. Conversion itself never requires a model."
)


def _require_client():
    client = chat_service.get_client()
    if client is None:
        raise HTTPException(status_code=422, detail=_NOT_CONFIGURED)
    return client


async def _one_workflow(file: UploadFile | None, project_id: str | None, workflow_id: str | None) -> tuple[str, bytes]:
    if project_id or workflow_id:
        if not (project_id and workflow_id):
            raise HTTPException(status_code=422, detail="Pass both project_id and workflow_id.")
        stored = project_service.get_workflow_file(project_id, workflow_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="Unknown project or workflow.")
        return stored
    if file is None:
        raise HTTPException(status_code=422, detail="Upload a workflow, or pass project_id and workflow_id.")
    validate_yxmd_file(file)
    return file.filename or "upload.yxmd", await read_upload(file)


@router.get("/status")
async def ai_status() -> dict:
    """Whether a model endpoint is configured, so the UI can show the opt-in note."""
    return {"enabled": chat_service.is_enabled()}


@router.post("/gaps")
async def gaps(
    file: UploadFile | None = File(None),
    project_id: str | None = Form(None),
    workflow_id: str | None = Form(None),
    opts: ConversionOptions = Depends(conversion_options),
) -> dict:
    """List what the converter couldn't finish for one workflow (no model call)."""
    name, content = await _one_workflow(file, project_id, workflow_id)
    try:
        ctx = await run_with_timeout(ai_completion.gap_summary, name, content, opts, label=f"Checking {name}")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    return ctx.to_dict()


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
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    except LLMRequestError as e:
        raise HTTPException(status_code=502, detail=f"Model endpoint error: {e}") from None


@router.post("/notes", response_class=PlainTextResponse)
async def notes(
    file: UploadFile | None = File(None),
    project_id: str | None = Form(None),
    workflow_id: str | None = Form(None),
    opts: ConversionOptions = Depends(conversion_options),
) -> PlainTextResponse:
    """Return the Markdown suggestions notes for one workflow, as a download."""
    client = _require_client()
    name, content = await _one_workflow(file, project_id, workflow_id)
    try:
        filename, markdown = await run_with_timeout(
            ai_completion.suggestions_markdown, name, content, client, opts, label=f"Notes for {name}"
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    except LLMRequestError as e:
        raise HTTPException(status_code=502, detail=f"Model endpoint error: {e}") from None
    return PlainTextResponse(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
