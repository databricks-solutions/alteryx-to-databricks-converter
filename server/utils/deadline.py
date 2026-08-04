"""Run blocking work in a worker thread under a deadline."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import HTTPException

from server.settings import settings

logger = logging.getLogger("a2d.server.deadline")

T = TypeVar("T")


async def run_with_timeout(
    func: Callable[..., T],
    *args: Any,
    timeout: float | None = None,
    label: str = "operation",
    **kwargs: Any,
) -> T:
    """Run ``func`` in a thread, raising HTTP 408 if it exceeds the deadline.

    Conversion, analysis and report generation are CPU-bound and correctly
    offloaded off the event loop — but a workflow that sends the parser or a
    generator into a pathological path would otherwise hold its worker thread
    forever. Enough of those exhaust the pool and the service stops answering
    healthy requests too.

    A caveat worth knowing: ``asyncio.wait_for`` cannot kill the underlying
    thread, so the work may continue in the background after the client is given
    a 408. This bounds the *client* wait and keeps the API responsive; it is not
    a hard resource kill. Guarding against genuinely unbounded loops still needs
    limits inside the converter itself.
    """
    limit = settings.conversion_timeout_seconds if timeout is None else timeout
    try:
        return await asyncio.wait_for(asyncio.to_thread(func, *args, **kwargs), timeout=limit)
    except TimeoutError:
        # asyncio.TimeoutError is an alias of TimeoutError on Python 3.11+.
        logger.warning("%s exceeded the %.0fs deadline", label, limit)
        raise HTTPException(
            status_code=408,
            detail=(
                f"{label} took longer than {limit:.0f}s and was abandoned. "
                f"Try a smaller workflow, or raise A2D_CONVERSION_TIMEOUT_SECONDS."
            ),
        ) from None
