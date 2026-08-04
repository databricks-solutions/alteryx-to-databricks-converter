"""History API — browse and manage past conversions.

**Tenancy: history is a SHARED team log, by design.**

In Databricks Apps this app runs as a single service principal, so the Lakebase
table has one database identity for every user. There is deliberately no
per-user scoping: everyone who can open the app sees the whole team's conversion
history and may delete any entry. That is the intended model — a shared record of
one migration effort — not an oversight.

Two consequences worth knowing before you deploy:

* Don't treat an entry as private. Workflow names and generated code are visible
  to every app user.
* Access control is the Databricks Apps permission on the app itself (the
  ``permissions:`` block in ``databricks.yml``). Grant app access only to the
  people who should see the estate.

If per-user history is ever needed, the change is an owner column populated from
the Apps forwarded-identity header plus a filter on list/get/delete.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from server.models.responses import HistoryListResponse
from server.services import history

router = APIRouter(prefix="/api", tags=["history"])


@router.get("/history", response_model=HistoryListResponse)
def list_history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    if not history.is_available():
        return HistoryListResponse(items=[], total=0)

    items, total = history.list_conversions(limit=limit, offset=offset)
    return HistoryListResponse(items=items, total=total)


@router.get("/history/{record_id}")
def get_history_detail(record_id: str):
    if not history.is_available():
        raise HTTPException(status_code=404, detail="History not configured")

    record = history.get_conversion(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Conversion not found")
    return record


@router.delete("/history/{record_id}")
def delete_history(record_id: str):
    """Delete one entry from the shared history.

    Any app user may delete any entry — see the module docstring on tenancy.
    """
    if not history.is_available():
        raise HTTPException(status_code=404, detail="History not configured")

    deleted = history.delete_conversion(record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversion not found")
    return {"ok": True}
