"""AI completion endpoints: the only routes that return model-written content.

Each takes one workflow, either uploaded (``file``, with any ``.yxmc`` it calls
in ``macros``) or from a saved project (``project_id`` + ``workflow_id``, which
brings the project's macros), and the same conversion options as Convert:

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
import re

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from lxml.etree import XMLSyntaxError
from starlette.concurrency import run_in_threadpool

from a2d.advisor import tracing
from a2d.advisor.completion import CompletionUnavailableError
from a2d.exceptions import A2dError
from server.models.requests import ConversionOptions, conversion_options
from server.services import ai_completion
from server.utils.deadline import run_with_timeout
from server.utils.headers import content_disposition
from server.utils.project_input import resolve_one_workflow

logger = logging.getLogger("a2d.server.routers.ai")

_TRACE_ID_RE = re.compile(r"tr-[0-9a-f]{8,64}|trace:/[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){1,2}/[0-9a-f]{8,64}")

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
    macros: list[UploadFile] = File(default=[]),
    opts: ConversionOptions = Depends(conversion_options),
) -> dict:
    """What the converter couldn't finish for one workflow (no model call)."""
    wf = await resolve_one_workflow(file, project_id, workflow_id, macros)
    name, content = wf.name, wf.content
    try:
        return await run_with_timeout(
            ai_completion.gap_summary, name, content, opts, wf.macros, label=f"Checking {name}"
        )
    except (ValueError, XMLSyntaxError, A2dError) as e:
        raise _bad_workflow(name, e) from None


@router.post("/complete")
async def complete(
    file: UploadFile | None = File(None),
    project_id: str | None = Form(None),
    workflow_id: str | None = Form(None),
    macros: list[UploadFile] = File(default=[]),
    opts: ConversionOptions = Depends(conversion_options),
) -> dict:
    """Return an AI-completed copy of the workflow's PySpark notebook."""
    client = _require_client()
    wf = await resolve_one_workflow(file, project_id, workflow_id, macros)
    name, content = wf.name, wf.content
    try:
        return await run_with_timeout(
            ai_completion.complete_workflow,
            name,
            content,
            client,
            opts,
            macros=wf.macros,
            label=f"AI completion for {name}",
        )
    except ai_completion.CompletionBusyError as e:
        raise HTTPException(status_code=429, detail=str(e)) from None
    except CompletionUnavailableError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    except (ValueError, XMLSyntaxError, A2dError) as e:
        raise _bad_workflow(name, e) from None


@router.post("/suggest")
async def suggest(
    node_id: int = Form(...),
    hint: str | None = Form(None),
    file: UploadFile | None = File(None),
    project_id: str | None = Form(None),
    workflow_id: str | None = Form(None),
    macros: list[UploadFile] = File(default=[]),
    opts: ConversionOptions = Depends(conversion_options),
) -> dict:
    """AI code for one step, for Review: a suggestion the reviewer accepts,
    edits or discards. PySpark only, like AI completion."""
    client = _require_client()
    if hint is not None and len(hint) > 2000:
        raise HTTPException(status_code=422, detail="The note is too long (2,000 characters at most).")
    wf = await resolve_one_workflow(file, project_id, workflow_id, macros)
    name, content = wf.name, wf.content
    try:
        return await run_with_timeout(
            ai_completion.suggest_step,
            name,
            content,
            client,
            node_id,
            opts,
            hint=hint,
            macros=wf.macros,
            label=f"AI suggestion for {name} step {node_id}",
        )
    except ai_completion.CompletionBusyError as e:
        raise HTTPException(status_code=429, detail=str(e)) from None
    except CompletionUnavailableError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    except (ValueError, XMLSyntaxError, A2dError) as e:
        raise _bad_workflow(name, e) from None


@router.post("/feedback")
async def feedback(payload: dict = Body(...)) -> dict:
    """Record what a reviewer did with a suggestion (``used``, ``edited`` or
    ``discarded``) on its MLflow trace. A no-op when AI tracing is off."""
    trace_id = payload.get("trace_id")
    outcome = payload.get("outcome")
    # "tr-<hex>" (experiment storage) or "trace:/<catalog>.<schema>[.<prefix>]/<hex>" (Unity Catalog).
    if not isinstance(trace_id, str) or not _TRACE_ID_RE.fullmatch(trace_id):
        raise HTTPException(status_code=422, detail="'trace_id' must be an MLflow trace id")
    if outcome not in tracing.OUTCOMES:
        raise HTTPException(status_code=422, detail=f"'outcome' must be one of {', '.join(tracing.OUTCOMES)}")
    recorded = await run_in_threadpool(tracing.log_outcome, trace_id, outcome)
    return {"recorded": recorded}


@router.get("/tracing")
async def tracing_status() -> dict:
    """Whether AI calls are traced to MLflow."""
    return {"enabled": await run_in_threadpool(tracing.enabled)}


@router.post("/notes", response_class=PlainTextResponse)
async def notes(
    file: UploadFile | None = File(None),
    project_id: str | None = Form(None),
    workflow_id: str | None = Form(None),
    macros: list[UploadFile] = File(default=[]),
    opts: ConversionOptions = Depends(conversion_options),
) -> PlainTextResponse:
    """Return the AI suggestions notes (Markdown) for one workflow, as a download."""
    client = _require_client()
    wf = await resolve_one_workflow(file, project_id, workflow_id, macros)
    name, content = wf.name, wf.content
    try:
        filename, markdown = await run_with_timeout(
            ai_completion.suggestions_markdown, name, content, client, opts, wf.macros, label=f"Notes for {name}"
        )
    except (ValueError, XMLSyntaxError, A2dError) as e:
        raise _bad_workflow(name, e) from None
    return PlainTextResponse(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": content_disposition(filename)},
    )
