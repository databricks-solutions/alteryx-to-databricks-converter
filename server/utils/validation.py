"""Shared validation utilities for server endpoints."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from fastapi import HTTPException, UploadFile

from server.settings import settings


def sanitize_filename(filename: str) -> str:
    """Strip directory components and dangerous characters from a filename."""
    name = PurePosixPath(filename).name
    name = re.sub(r"[^\w\-.]", "_", name)
    return name or "upload.yxmd"


def validate_yxmd_file(file: UploadFile) -> None:
    """Validate that an uploaded file is a .yxmd workflow."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")
    suffix = PurePosixPath(file.filename).suffix.lower()
    if suffix not in settings.allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"File {file.filename} must be a .yxmd workflow",
        )


async def read_upload(file: UploadFile) -> bytes:
    """Read an uploaded file with streaming size validation."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(65_536)  # 64 KB chunks
        if not chunk:
            break
        total += len(chunk)
        if total > settings.max_upload_size_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File {file.filename} exceeds maximum size of {settings.max_upload_size_bytes // (1024 * 1024)} MB",
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def validate_and_read_files(files: list[UploadFile]) -> list[tuple[str, bytes]]:
    """Validate and read a list of uploaded .yxmd files.

    Checks file count, validates extensions, and reads content with size limits.
    Returns list of (filename, content) tuples.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    if len(files) > settings.max_batch_files:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files: maximum is {settings.max_batch_files}",
        )

    file_data: list[tuple[str, bytes]] = []
    for f in files:
        validate_yxmd_file(f)
        content = await read_upload(f)
        file_data.append((f.filename, content))

    return file_data
