"""Who is making a request.

Databricks Apps signs users in and passes their identity to the app in
``X-Forwarded-Email`` (and ``X-Forwarded-Preferred-Username``). Run anywhere
else, there's no signed-in user.
"""

from __future__ import annotations

from starlette.requests import HTTPConnection


def current_user(request: HTTPConnection) -> str | None:
    email = request.headers.get("x-forwarded-email") or request.headers.get("x-forwarded-preferred-username")
    return email.strip().lower() if email and email.strip() else None


def note_usage(request: HTTPConnection, **details) -> None:
    """Add details to the usage event recorded for this request (how many
    workflows, the coverage, the project). Values must be JSON-friendly."""
    current = getattr(request.state, "usage", None) or {}
    current.update({k: v for k, v in details.items() if v is not None})
    request.state.usage = current
