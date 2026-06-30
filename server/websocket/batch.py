"""WebSocket endpoint for real-time batch progress."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from server.services.batch import JobStatus, get_job, subscribe, unsubscribe

logger = logging.getLogger("a2d.server.websocket.batch")

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

    # Create a queue for this subscriber
    queue: asyncio.Queue = asyncio.Queue()
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
