"""Conversion endpoints — single file and batch (multi-format)."""

from __future__ import annotations

import asyncio
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
        result = await asyncio.to_thread(
            convert_file,
            file_bytes,
            file.filename,
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
                    zf.writestr(
                        f"{workflow_folder}/{fmt_key}/{f['filename']}",
                        f["content"],
                    )

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="batch-{job_id}.zip"'},
    )
