"""Advisory migration-chat endpoints — discussion and report generation only.

Every route here is read-only with respect to converted output: the assistant
returns text, and the report is delivered as a standalone Markdown attachment.
No route can modify generated code.

AI is opt-in. Without a configured FMAPI endpoint these routes return HTTP 422
with an actionable message rather than silently degrading.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse

from a2d.advisor.llm_client import LLMRequestError
from server.services import chat as chat_service
from server.utils.deadline import run_with_timeout
from server.utils.validation import read_upload, validate_yxmd_file

logger = logging.getLogger("a2d.server.routers.chat")

router = APIRouter(prefix="/api", tags=["chat"])

_NOT_CONFIGURED = (
    "AI suggestions are opt-in and no Foundation Model API endpoint is configured. "
    "Set A2D_FMAPI_ENDPOINT (and A2D_FMAPI_TOKEN if the endpoint needs a token) to "
    "enable the migration assistant. Conversion itself never requires a model."
)


def _require_client():
    client = chat_service.get_client()
    if client is None:
        raise HTTPException(status_code=422, detail=_NOT_CONFIGURED)
    return client


def _require_session(session_id: str):
    session = chat_service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Unknown chat session {session_id!r}")
    return session


@router.get("/chat/status")
async def chat_status() -> dict:
    """Report whether the assistant is available, so the UI can show an opt-in hint."""
    return {"enabled": chat_service.is_enabled()}


@router.post("/chat")
async def start_chat(
    file: UploadFile = File(...),
    output_format: str = Form("pyspark"),
) -> dict:
    """Start a grounded chat session about one uploaded workflow.

    Converts the workflow deterministically, collects the migration facts (gaps
    and conversion decisions) and returns the session with an opening summary.
    """
    client = _require_client()
    validate_yxmd_file(file)
    content = await read_upload(file)

    try:
        session = await run_with_timeout(
            chat_service.create_session,
            file.filename or "upload.yxmd",
            content,
            output_format,
            label=f"Starting assistant session for {file.filename}",
            client=client,
        )
    except ValueError as e:
        logger.warning("Validation error starting chat: %s", e)
        raise HTTPException(status_code=422, detail=str(e)) from None
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error starting chat session")
        raise HTTPException(status_code=500, detail="Internal chat error") from None

    return chat_service.session_payload(session)


@router.post("/chat/{session_id}/message")
async def send_message(session_id: str, message: str = Body(..., embed=True)) -> dict:
    """Send one user turn and return the assistant's reply."""
    _require_client()
    session = _require_session(session_id)

    text = (message or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="message must not be empty")

    session.record("user", text)
    try:
        reply = await run_with_timeout(session.chat.ask, text, label="Assistant reply")
    except LLMRequestError as e:
        logger.warning("Chat turn failed for %s: %s", session_id, e)
        raise HTTPException(status_code=502, detail=f"Model endpoint error: {e}") from None
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error on chat turn")
        raise HTTPException(status_code=500, detail="Internal chat error") from None

    session.record("assistant", reply)
    return {"session_id": session_id, "reply": reply}


@router.post("/chat/{session_id}/report", response_class=PlainTextResponse)
async def generate_report(session_id: str, answers: dict[str, str] | None = Body(default=None)) -> PlainTextResponse:
    """Generate the standalone Markdown suggestions report for this session.

    Returned as a downloadable attachment — a separate document that is never
    merged into the generated code.
    """
    _require_client()
    session = _require_session(session_id)

    try:
        markdown = await run_with_timeout(session.chat.generate_report, answers or None, label="Report generation")
    except LLMRequestError as e:
        logger.warning("Report generation failed for %s: %s", session_id, e)
        raise HTTPException(status_code=502, detail=f"Model endpoint error: {e}") from None
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error generating report")
        raise HTTPException(status_code=500, detail="Internal chat error") from None

    filename = f"{session.context.workflow_name}_suggestions.md"
    return PlainTextResponse(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
