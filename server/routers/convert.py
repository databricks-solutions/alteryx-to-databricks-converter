"""Conversion endpoints — single file and batch (multi-format)."""

from __future__ import annotations

import io
import logging
import zipfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from server.models.requests import ConversionOptions, conversion_options
from server.models.responses import (
    BatchStartResponse,
    BatchStatusResponse,
    ConversionResponse,
)
from server.services import batch as batch_service
from server.services.conversion import convert_file
from server.settings import settings
from server.utils.deadline import run_with_timeout
from server.utils.validation import read_upload, validate_and_read_files, validate_yxmd_file

logger = logging.getLogger("a2d.server.routers.convert")

router = APIRouter(prefix="/api", tags=["convert"])


@router.post("/convert", response_model=ConversionResponse)
async def convert_single(
    file: UploadFile = File(...),
    opts: ConversionOptions = Depends(conversion_options),
) -> ConversionResponse:
    validate_yxmd_file(file)
    file_bytes = await read_upload(file)

    logger.info("Converting %s (multi-format, size=%d bytes)", file.filename, len(file_bytes))
    try:
        result = await run_with_timeout(
            convert_file,
            file_bytes,
            file.filename,
            label=f"Converting {file.filename}",
            catalog_name=opts.catalog_name,
            schema_name=opts.schema_name,
            include_comments=opts.include_comments,
            include_expression_audit=opts.include_expression_audit,
            include_performance_hints=opts.include_performance_hints,
            generate_ddl=opts.generate_ddl,
            generate_dab=opts.generate_dab,
            expand_macros=opts.expand_macros,
        )
    except ValueError as e:
        logger.warning("Validation error converting %s: %s", file.filename, e)
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        # Already an HTTP response (e.g. the 408 deadline) — don't rewrite it as a 500.
        raise
    except Exception:
        logger.exception("Unexpected error converting %s", file.filename)
        raise HTTPException(status_code=500, detail="Internal conversion error")

    logger.info("Successfully converted %s (best_format=%s)", file.filename, result.get("best_format"))
    return ConversionResponse(**result)


@router.post("/convert/batch", response_model=BatchStartResponse)
async def convert_batch(
    files: list[UploadFile] = File(...),
    opts: ConversionOptions = Depends(conversion_options),
) -> BatchStartResponse:
    file_data = await validate_and_read_files(files)

    logger.info("Starting batch conversion: %d files (multi-format)", len(file_data))
    job_id = await batch_service.create_batch_job(
        file_data,
        catalog_name=opts.catalog_name,
        schema_name=opts.schema_name,
        include_comments=opts.include_comments,
        include_expression_audit=opts.include_expression_audit,
        include_performance_hints=opts.include_performance_hints,
        generate_ddl=opts.generate_ddl,
        generate_dab=opts.generate_dab,
        expand_macros=opts.expand_macros,
    )

    return BatchStartResponse(job_id=job_id, total_files=len(file_data))


@router.get("/convert/batch/{job_id}", response_model=BatchStatusResponse)
async def batch_status(job_id: str) -> BatchStatusResponse:
    job = batch_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return BatchStatusResponse(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        total=job.total,
        file_results=job.file_results,
        batch_metrics=job.batch_metrics,
        errors_by_kind=job.errors_by_kind,
    )


@router.post("/convert/batch/{job_id}/cancel")
async def cancel_batch(job_id: str) -> dict:
    """Stop a running batch conversion.

    The UI previously "cancelled" by closing its WebSocket while the server kept
    converting, so the user was told something untrue and the compute was wasted.
    Cancellation stops work after the file currently in flight — asyncio cannot
    interrupt the thread running one conversion — which is what the UI now says.
    """
    job = batch_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not batch_service.cancel_job(job_id):
        raise HTTPException(
            status_code=409,
            detail=f"Job is already {job.status.value} and cannot be cancelled",
        )

    logger.info("Batch job %s cancelled", job_id)
    return {"job_id": job_id, "status": batch_service.JobStatus.CANCELLED.value}


@router.get("/convert/batch/{job_id}/download")
async def batch_download(job_id: str) -> StreamingResponse:
    """Download all generated files from a completed batch job as a ZIP.

    Layout: ``<workflow>/<format>/<filename>`` — every workflow's per-format
    outputs are organized into format-named subfolders.
    """
    job = batch_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != batch_service.JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Job not completed yet")

    # The archive is assembled in memory, so it needs a ceiling: a full batch
    # (max_batch_files uploads x 5 formats, plus optional DDL/DAB) could otherwise
    # allocate gigabytes. Checked as we write so we stop at the limit instead of
    # after the damage is done.
    max_bytes = settings.max_zip_size_bytes
    uncompressed_bytes = 0
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fr in job.file_results:
            if not fr.get("success"):
                continue
            workflow_folder = fr["workflow_name"]
            formats_dict = fr.get("formats") or {}
            for fmt_key, fmt_result in formats_dict.items():
                if not isinstance(fmt_result, dict):
                    continue
                if fmt_result.get("status") != "success":
                    continue
                for f in fmt_result.get("files", []):
                    # Check the UNCOMPRESSED size before writing. Measuring the
                    # archive buffer alone let highly compressible output through:
                    # generated code compresses ~10x, so a small ZIP could still
                    # expand to gigabytes on the client, and a single oversized
                    # entry was fully allocated before being rejected.
                    content = f["content"]
                    uncompressed_bytes += len(content.encode("utf-8", errors="replace"))
                    if uncompressed_bytes > max_bytes:
                        logger.warning(
                            "Batch %s exceeded %d uncompressed bytes — refusing to build the archive",
                            job_id,
                            max_bytes,
                        )
                        raise HTTPException(
                            status_code=413,
                            detail=(
                                f"The generated output for this batch exceeds the "
                                f"{max_bytes // (1024 * 1024)} MB limit. Download individual "
                                f"workflows instead, or raise A2D_MAX_ZIP_SIZE_BYTES."
                            ),
                        )
                    zf.writestr(
                        f"{workflow_folder}/{fmt_key}/{f['filename']}",
                        content,
                    )
                    if buf.tell() > max_bytes:
                        logger.warning(
                            "Batch %s ZIP exceeded %d bytes — refusing to build it",
                            job_id,
                            max_bytes,
                        )
                        raise HTTPException(
                            status_code=413,
                            detail=(
                                f"The archive for this batch exceeds the "
                                f"{max_bytes // (1024 * 1024)} MB limit. Download individual "
                                f"workflows instead, or raise A2D_MAX_ZIP_SIZE_BYTES."
                            ),
                        )

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="batch-{job_id}.zip"'},
    )
