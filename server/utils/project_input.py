"""Resolve an endpoint's input files from either a saved project or an upload.

The multi-file analysis endpoints (analyze, assess, savings, readiness,
portfolio) accept either a fresh upload (today's behavior) or a ``project_id``
that sources the already-stored estate — so a user uploads once and every screen
reads the same files without re-providing them. This helper centralizes that
branch so each router stays a couple of lines and behaves identically.
"""

from __future__ import annotations

from fastapi import HTTPException, UploadFile

from server.services import project as project_service
from server.utils.validation import validate_and_read_files


async def resolve_input_files(
    files: list[UploadFile],
    project_id: str | None,
) -> list[tuple[str, bytes]]:
    """Return ``[(file_name, bytes)]`` from the project when ``project_id`` is
    given, otherwise from the uploaded files.

    Raises 404 when the project is unknown or projects are unavailable, and 422
    when the project exists but has no workflows — so a project-driven call never
    silently falls back to an empty analysis.
    """
    if project_id:
        stored = project_service.get_project_files(project_id)
        if stored is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown project {project_id!r}, or projects are not available on this server.",
            )
        if not stored:
            raise HTTPException(status_code=422, detail="This project has no workflows to analyze yet.")
        return stored
    return await validate_and_read_files(files)
