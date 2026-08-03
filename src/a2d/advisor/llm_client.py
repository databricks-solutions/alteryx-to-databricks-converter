"""Opt-in Foundation Model API (FMAPI) client for *advisory* output only.

Nothing in a2d calls a model unless an operator explicitly configures an FMAPI
endpoint. There is no default endpoint and no implicit fallback: with no
configuration, :func:`resolve_client` returns ``None`` and callers must degrade
to a deterministic message. This keeps the converter's promise that a default
run is entirely offline.

The client's only capability is chat completion returning **text**. It cannot
construct IR nodes, edit files, or feed anything back into the conversion
pipeline — advisory text is the whole contract.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

logger = logging.getLogger("a2d.advisor.llm_client")

# Env vars an operator sets to opt in. Endpoint is required; the token is
# optional because Databricks Apps/notebooks can supply workspace credentials.
ENV_ENDPOINT = "A2D_FMAPI_ENDPOINT"
ENV_TOKEN = "A2D_FMAPI_TOKEN"

DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_TOKENS = 1500


class LLMNotConfiguredError(RuntimeError):
    """Raised when an advisory feature is used without an FMAPI endpoint."""

    def __init__(self, detail: str = "") -> None:
        super().__init__(
            detail
            or (
                "No Foundation Model API endpoint configured. AI suggestions are "
                f"opt-in: set {ENV_ENDPOINT} (and {ENV_TOKEN} if the endpoint needs "
                "a token) to enable them. Conversion itself never requires a model."
            )
        )


class LLMRequestError(RuntimeError):
    """Raised when a configured endpoint fails to answer."""


@dataclass
class ChatMessage:
    """One turn in an advisory conversation."""

    role: str  # "system" | "user" | "assistant"
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@runtime_checkable
class AdvisoryClient(Protocol):
    """Text-in/text-out advisory model. Deliberately minimal."""

    def chat(self, messages: list[ChatMessage], *, max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
        """Return the assistant's reply text for *messages*."""
        ...


@dataclass
class FMAPIClient:
    """Calls a Databricks Foundation Model API serving endpoint.

    ``endpoint`` is the full serving-endpoint invocations URL. ``token`` is a
    bearer token; when omitted the client tries the Databricks SDK's ambient
    credentials (works inside Databricks Apps under a service principal).
    """

    endpoint: str
    token: str | None = None
    timeout: float = DEFAULT_TIMEOUT
    _resolved_token: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.endpoint:
            raise LLMNotConfiguredError()

    def _auth_token(self) -> str | None:
        if self.token:
            return self.token
        if self._resolved_token is not None:
            return self._resolved_token
        # Ambient workspace credentials (Databricks Apps / notebooks). Optional:
        # a plain-token endpoint works without the SDK installed.
        try:
            from databricks.sdk import WorkspaceClient

            cfg = WorkspaceClient().config
            headers = cfg.authenticate() or {}
            bearer = headers.get("Authorization", "")
            self._resolved_token = bearer.removeprefix("Bearer ").strip() or None
        except Exception as exc:
            logger.debug("No ambient Databricks credentials available: %s", exc)
            self._resolved_token = None
        return self._resolved_token

    def chat(self, messages: list[ChatMessage], *, max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
        payload = json.dumps({"messages": [m.to_dict() for m in messages], "max_tokens": max_tokens}).encode("utf-8")

        headers = {"Content-Type": "application/json"}
        token = self._auth_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        request = urllib.request.Request(self.endpoint, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise LLMRequestError(f"FMAPI endpoint returned HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LLMRequestError(f"Could not reach the FMAPI endpoint: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise LLMRequestError(f"FMAPI endpoint returned invalid JSON: {exc}") from exc

        return _extract_text(body)


def _extract_text(body: dict) -> str:
    """Pull assistant text out of an OpenAI-compatible serving response."""
    choices = body.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
            if isinstance(first.get("text"), str):
                return first["text"]
    # Some endpoints return {"predictions": [...]} or a bare string.
    predictions = body.get("predictions")
    if isinstance(predictions, list) and predictions and isinstance(predictions[0], str):
        return predictions[0]
    raise LLMRequestError(f"Unrecognized FMAPI response shape: {sorted(body)[:6]}")


def resolve_client(
    endpoint: str | None = None,
    token: str | None = None,
) -> AdvisoryClient | None:
    """Build a client from explicit args or env, or ``None`` if not configured.

    Returning ``None`` (rather than raising) lets callers show a friendly opt-in
    message; use :class:`LLMNotConfiguredError` when a model is truly required.
    """
    resolved_endpoint = (endpoint or os.environ.get(ENV_ENDPOINT, "")).strip()
    if not resolved_endpoint:
        return None
    resolved_token = (token or os.environ.get(ENV_TOKEN, "")).strip() or None
    return FMAPIClient(endpoint=resolved_endpoint, token=resolved_token)
