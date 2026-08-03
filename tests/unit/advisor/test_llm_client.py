"""Tests for the opt-in FMAPI advisory client."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from a2d.advisor.llm_client import (
    ENV_ENDPOINT,
    ENV_TOKEN,
    ChatMessage,
    FMAPIClient,
    LLMNotConfiguredError,
    LLMRequestError,
    _extract_text,
    resolve_client,
)


class TestOptIn:
    def test_no_env_means_no_client(self, monkeypatch):
        """The default posture is offline: nothing is configured, nothing runs."""
        monkeypatch.delenv(ENV_ENDPOINT, raising=False)
        assert resolve_client() is None

    def test_blank_endpoint_is_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv(ENV_ENDPOINT, "   ")
        assert resolve_client() is None

    def test_env_endpoint_builds_client(self, monkeypatch):
        monkeypatch.setenv(ENV_ENDPOINT, "https://example.invalid/invocations")
        monkeypatch.setenv(ENV_TOKEN, "tok")
        client = resolve_client()
        assert isinstance(client, FMAPIClient)
        assert client.endpoint == "https://example.invalid/invocations"
        assert client.token == "tok"

    def test_explicit_args_win_over_env(self, monkeypatch):
        monkeypatch.setenv(ENV_ENDPOINT, "https://from-env.invalid/x")
        client = resolve_client("https://explicit.invalid/y", "t2")
        assert isinstance(client, FMAPIClient)
        assert client.endpoint == "https://explicit.invalid/y"

    def test_empty_endpoint_raises(self):
        with pytest.raises(LLMNotConfiguredError):
            FMAPIClient(endpoint="")

    def test_not_configured_error_mentions_env_var(self):
        assert ENV_ENDPOINT in str(LLMNotConfiguredError())


class TestResponseParsing:
    def test_openai_chat_shape(self):
        body = {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}
        assert _extract_text(body) == "hi"

    def test_completion_text_shape(self):
        assert _extract_text({"choices": [{"text": "hello"}]}) == "hello"

    def test_predictions_shape(self):
        assert _extract_text({"predictions": ["yo"]}) == "yo"

    def test_unknown_shape_raises(self):
        with pytest.raises(LLMRequestError, match="Unrecognized"):
            _extract_text({"weird": 1})


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


class TestChatCall:
    def test_chat_posts_and_returns_text(self):
        client = FMAPIClient(endpoint="https://example.invalid/invocations", token="t")
        payload = {"choices": [{"message": {"content": "suggested answer"}}]}
        with patch("urllib.request.urlopen", return_value=_FakeResponse(payload)) as mock:
            out = client.chat([ChatMessage(role="user", content="q")])
        assert out == "suggested answer"
        request = mock.call_args[0][0]
        assert request.get_header("Authorization") == "Bearer t"
        assert json.loads(request.data)["messages"] == [{"role": "user", "content": "q"}]

    def test_network_error_becomes_llm_request_error(self):
        import urllib.error

        client = FMAPIClient(endpoint="https://example.invalid/invocations", token="t")
        with (
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")),
            pytest.raises(LLMRequestError, match="Could not reach"),
        ):
            client.chat([ChatMessage(role="user", content="q")])

    def test_invalid_json_becomes_llm_request_error(self):
        class BadResponse(_FakeResponse):
            def read(self) -> bytes:
                return b"not json"

        client = FMAPIClient(endpoint="https://example.invalid/invocations", token="t")
        with (
            patch("urllib.request.urlopen", return_value=BadResponse({})),
            pytest.raises(LLMRequestError, match="invalid JSON"),
        ):
            client.chat([ChatMessage(role="user", content="q")])
