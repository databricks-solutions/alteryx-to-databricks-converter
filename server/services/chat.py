"""Migration-chat service — grounded advisory sessions over a converted workflow.

Sessions live in memory (like batch jobs) and hold a
:class:`~a2d.advisor.context.MigrationContext` plus the transcript. The service
never writes to disk and never returns generated code for editing: replies are
text and the report is a standalone Markdown document.

AI is opt-in. When no FMAPI endpoint is configured, :func:`get_client` returns
``None`` and the routers turn that into a clear 422 instead of quietly doing
nothing.
"""

from __future__ import annotations

import logging
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from a2d.advisor.chat import MigrationChat
from a2d.advisor.context import MigrationContext, build_migration_context
from a2d.advisor.llm_client import AdvisoryClient, resolve_client
from a2d.config import ConversionConfig, OutputFormat
from a2d.pipeline import ConversionPipeline
from server.settings import settings
from server.utils.validation import sanitize_filename

logger = logging.getLogger("a2d.server.services.chat")

# Sessions are cheap (facts + transcript) but shouldn't leak forever.
SESSION_TTL_SECONDS = 3600
MAX_SESSIONS = 200


@dataclass
class ChatSession:
    """One advisory conversation about one uploaded workflow."""

    session_id: str
    context: MigrationContext
    chat: MigrationChat
    created_at: float = field(default_factory=time.time)
    messages: list[dict] = field(default_factory=list)

    def record(self, role: str, content: str) -> dict:
        message = {"role": role, "content": content, "at": time.time()}
        self.messages.append(message)
        return message


_sessions: dict[str, ChatSession] = {}
# Ids dropped by TTL/cap, kept so the API can answer 410 instead of 404.
_evicted: set[str] = set()
_lock = threading.Lock()


def get_client(endpoint: str | None = None, token: str | None = None) -> AdvisoryClient | None:
    """Resolve the advisory client from the request, then server settings."""
    return resolve_client(
        endpoint or settings.fmapi_endpoint or None,
        token or settings.fmapi_token or None,
    )


def is_enabled() -> bool:
    """True when an FMAPI endpoint is configured somewhere."""
    return get_client() is not None


def _prune_locked() -> None:
    cutoff = time.time() - SESSION_TTL_SECONDS
    stale = [sid for sid, s in _sessions.items() if s.created_at < cutoff]
    for sid in stale:
        del _sessions[sid]
        _evicted.add(sid)
    # Hard cap: drop the oldest sessions if we're still over budget.
    if len(_sessions) > MAX_SESSIONS:
        for sid, _ in sorted(_sessions.items(), key=lambda kv: kv[1].created_at)[: len(_sessions) - MAX_SESSIONS]:
            del _sessions[sid]
            _evicted.add(sid)
        logger.warning("Chat session cap reached — evicted the oldest sessions")


def was_evicted(session_id: str) -> bool:
    """True if this session existed and was dropped (vs never existing).

    Lets the API answer 410 Gone rather than 404, so a client mid-conversation is
    told to start a new session instead of being left to guess whether it sent a
    bad id.
    """
    with _lock:
        return session_id in _evicted


def build_context(filename: str, content: bytes, output_format: str = "pyspark") -> MigrationContext:
    """Convert an uploaded workflow and collect its advisory context.

    Raises :class:`ValueError` for an unknown format or unparseable workflow.
    """
    try:
        fmt = OutputFormat(output_format)
    except ValueError as exc:
        raise ValueError(f"unknown output_format {output_format!r}") from exc

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / sanitize_filename(filename)
        path.write_bytes(content)

        config = ConversionConfig(input_path=path, output_dir=Path(tmpdir) / "out", output_format=fmt)
        result = ConversionPipeline(config).convert(path)
        generated_code = "\n".join(f.content for f in result.output.files)

        return build_migration_context(
            result.dag,
            workflow_name=path.stem,
            output_format=fmt.value,
            format_warnings=list(result.output.warnings),
            generated_code=generated_code,
            coverage=result.output.stats.get("coverage_percentage"),
            confidence=result.confidence.overall if result.confidence else None,
        )


def create_session(
    filename: str,
    content: bytes,
    output_format: str = "pyspark",
    *,
    client: AdvisoryClient | None = None,
) -> ChatSession:
    """Start a grounded chat session. Caller must ensure a client exists."""
    resolved = client or get_client()
    if resolved is None:  # pragma: no cover - routers check first
        raise ValueError("no FMAPI endpoint configured")

    context = build_context(filename, content, output_format)
    session = ChatSession(
        session_id=uuid.uuid4().hex,
        context=context,
        chat=MigrationChat(context=context, client=resolved),
    )
    session.record("assistant", session.chat.opening_summary())

    with _lock:
        _prune_locked()
        _sessions[session.session_id] = session

    logger.info(
        "Chat session %s for %s [%s]: %d gaps",
        session.session_id,
        filename,
        output_format,
        len(context.gaps),
    )
    return session


def get_session(session_id: str) -> ChatSession | None:
    with _lock:
        return _sessions.get(session_id)


def clear_sessions() -> None:
    """Drop every session (used by tests)."""
    with _lock:
        _sessions.clear()
        _evicted.clear()


def session_payload(session: ChatSession) -> dict:
    """Serialize a session for the API."""
    return {
        "session_id": session.session_id,
        "context": session.context.to_dict(),
        "messages": [{"role": m["role"], "content": m["content"]} for m in session.messages],
        "clarifying_questions": session.chat.clarifying_questions(),
    }
