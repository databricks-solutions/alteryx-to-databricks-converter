"""Usage page API: who used the app for what (see :mod:`server.services.usage`).

* ``GET /api/usage/access``: whether the signed-in user can see the page, and
  whether tracking is on, so the page can say why it's empty.
* ``GET /api/usage?days=30``: the summary; 403 unless the user is in
  ``A2D_USAGE_ADMINS``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool

from server.services import db, usage
from server.utils.identity import current_user

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get("/access")
async def access(request: Request) -> dict:
    user = current_user(request)
    return {
        "user": user,
        "allowed": usage.can_view(user),
        "admins_configured": bool(usage.admins()),
        "tracking": usage.settings.usage_tracking,
        "database": bool(db.resolve_backend()),
    }


@router.get("")
async def summary(request: Request, days: int = Query(30, ge=1, le=3650)) -> dict:
    if not usage.can_view(current_user(request)):
        raise HTTPException(status_code=403, detail="Only the people in A2D_USAGE_ADMINS can see usage.")
    return await run_in_threadpool(usage.summary, days)
