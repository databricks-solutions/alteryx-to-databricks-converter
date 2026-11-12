"""Resolve an endpoint's input files from either a saved project or an upload.

The multi-file endpoints (analyze, assess, savings, readiness, portfolio, batch
convert) accept either a fresh upload or a ``project_id`` that sources the stored
estate, so a user uploads once and every step reads the same files. This helper
keeps that branch identical everywhere:

* a project read runs in a worker thread (the database driver is synchronous),
* a project-sourced run gets the same file-count and total-size limits as an
  upload, and
* "no database" (503), "unknown project" (404) and "empty project" (422) stay
  distinct, so a caller never silently analyzes nothing.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from server.services import project as project_service
from server.settings import settings
from server.utils.validation import validate_and_read_files

PROJECTS_NOT_CONFIGURED = (
    "Saved projects need a database, and this server doesn't have one configured. "
    "The app still works with a project kept in the browser."
)
PROJECTS_UNREACHABLE = "Saved projects are temporarily unavailable: the database isn't responding. Try again shortly."


def require_projects() -> None:
    """Raise 503 unless saved projects can be used right now, saying which case it is."""
    if project_service.is_available():
        return
    if project_service.is_configured():
        raise HTTPException(status_code=503, detail=PROJECTS_UNREACHABLE)
    raise HTTPException(status_code=503, detail=PROJECTS_NOT_CONFIGURED)


def check_project_id(project_id: str) -> None:
    """404 for an id that can't be a project (saves a database round trip)."""
    try:
        uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown project {project_id!r}") from None


def _enforce_limits(files: list[tuple[str, bytes]]) -> None:
    if len(files) > settings.max_batch_files:
        raise HTTPException(
            status_code=400,
            detail=f"This project has {len(files)} workflows; one run takes at most {settings.max_batch_files}. "
            "Select fewer workflows.",
        )
    max_total = settings.max_upload_size_bytes * settings.max_batch_files
    if sum(len(content) for _, content in files) > max_total:
        raise HTTPException(
            status_code=400,
            detail=f"The selected workflows exceed the total size limit of {max_total // (1024 * 1024)} MB for one run.",
        )


async def resolve_input_files(
    files: list[UploadFile],
    project_id: str | None,
    *,
    only: set[str] | None = None,
) -> list[tuple[str, bytes]]:
    """Return ``[(file_name, bytes)]`` from the project when ``project_id`` is
    given, otherwise from the uploaded files.

    ``only`` narrows a project run to those file names (all must exist). Sending
    uploads together with a ``project_id`` is rejected rather than ignored.
    """
    if not project_id:
        return await validate_and_read_files(files)
    if any(getattr(f, "filename", None) for f in files):
        raise HTTPException(status_code=422, detail="Send either uploaded files or a project_id, not both.")
    require_projects()
    check_project_id(project_id)
    stored = await run_in_threadpool(project_service.get_project_files, project_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"Unknown project {project_id!r}")
    if only is not None:
        names = {name for name, _ in stored}
        unknown = sorted(only - names)
        if unknown:
            raise HTTPException(status_code=422, detail=f"Not in this project: {', '.join(unknown)}")
        stored = [(name, content) for name, content in stored if name in only]
    if not stored:
        raise HTTPException(status_code=422, detail="This project has no workflows to analyze yet.")
    _enforce_limits(stored)
    return stored
