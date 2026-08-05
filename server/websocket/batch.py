"""WebSocket endpoint for real-time batch progress."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from server.services.batch import JobStatus, get_job, subscribe, unsubscribe

logger = logging.getLogger("a2d.server.websocket.batch")

# Per-subscriber event backlog cap (see the queue construction below).
MAX_QUEUED_EVENTS = 500

router = APIRouter(tags=["websocket"])


@router.websocket("/api/ws/batch/{job_id}")
async def batch_ws(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()

    job = get_job(job_id)
    if not job:
        logger.warning("WebSocket: job %s not found", job_id)
        await websocket.send_json({"type": "error", "message": "Job not found"})
        await websocket.close()
        return

    # Bounded so a slow or stalled client can't grow the queue without limit.
    # Producers already tolerate a failed put (see services/batch.py), so a full
    # queue drops progress events for that subscriber rather than the server
    # accumulating every message for a browser that stopped reading. The cap is
    # generous relative to max_batch_files so normal runs never hit it.
    queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUED_EVENTS)
    subscribe(job_id, queue)
    logger.info("WebSocket subscriber connected for job %s", job_id)

    try:
        # Send any already-completed results
        for fr in job.file_results:
            await websocket.send_json({"type": "file_complete", **fr})

        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            await websocket.send_json(
                {
                    "type": "batch_complete",
                    "batch_metrics": job.batch_metrics,
                    "errors_by_kind": job.errors_by_kind,
                    "file_results": job.file_results,
                }
            )
            return

        # Stream updates as they arrive
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=60.0)
                await websocket.send_json(msg)
                if msg.get("type") in ("batch_complete", "error"):
                    break
            except asyncio.TimeoutError:
                # Send keepalive
                await websocket.send_json(
                    {
                        "type": "progress",
                        "current": job.progress,
                        "total": job.total,
                        "filename": job.current_filename,
                    }
                )
    except WebSocketDisconnect:
        logger.info("WebSocket subscriber disconnected for job %s", job_id)
    finally:
        unsubscribe(job_id, queue)
