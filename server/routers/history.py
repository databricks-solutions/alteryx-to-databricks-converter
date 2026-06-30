"""History API — browse and manage past conversions."""

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
    if not history.is_available():
        raise HTTPException(status_code=404, detail="History not configured")

    deleted = history.delete_conversion(record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversion not found")
    return {"ok": True}
