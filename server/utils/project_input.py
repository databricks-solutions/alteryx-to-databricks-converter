"""Resolve an endpoint's input files from either a saved project or an upload.

The multi-file endpoints (analyze, assess, savings, readiness, portfolio, batch
convert) accept either a fresh upload or a ``project_id`` that sources the stored
estate, so a user uploads once and every step reads the same files. The
single-workflow endpoints (convert, review, advise, AI) take a ``project_id`` +
``workflow_id`` the same way. These helpers keep that branch identical
everywhere:

* a project read runs in a worker thread (the database driver is synchronous),
* a project-sourced run gets the same file-count and total-size limits as an
  upload, and
* "no database" (503), "unknown project" (404) and "empty project" (422) stay
  distinct, so a caller never silently analyzes nothing, and
* a run gets the project's macros (``.yxmc``) even when it only processes some
  of its workflows, so a macro call resolves the same way in every step. An
  upload brings its macros as ``.yxmc`` files among the uploads, or in a
  separate ``macros`` field next to a single workflow.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from server.services import project as project_service
from server.settings import settings
from server.utils.package import macro_files
from server.utils.validation import read_upload, validate_and_read_files, validate_yxmd_file

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


@dataclass(frozen=True)
class RunInputs:
    """What a multi-file run processes, and the macros those workflows may call."""

    files: list[tuple[str, bytes]]
    macros: list[tuple[str, bytes]]


@dataclass(frozen=True)
class OneWorkflow:
    """One workflow for a single-workflow step, and the macros it may call."""

    name: str
    content: bytes
    macros: list[tuple[str, bytes]]


async def _project_files(project_id: str) -> list[tuple[str, bytes]]:
    require_projects()
    check_project_id(project_id)
    stored = await run_in_threadpool(project_service.get_project_files, project_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"Unknown project {project_id!r}")
    return stored


async def _uploaded_macros(macros: list[UploadFile]) -> list[tuple[str, bytes]]:
    sent = [m for m in macros if getattr(m, "filename", None)]
    if not sent:
        return []
    read = await validate_and_read_files(sent)
    not_macros = [name for name, _ in read if not name.lower().endswith(".yxmc")]
    if not_macros:
        raise HTTPException(status_code=422, detail=f"Only .yxmc macros go in 'macros': {', '.join(not_macros)}")
    return read


async def resolve_run_inputs(
    files: list[UploadFile],
    project_id: str | None,
    *,
    only: set[str] | None = None,
    macros: list[UploadFile] | None = None,
) -> RunInputs:
    """The files a run processes, plus the macros available to them.

    From a project: its files (narrowed to ``only``, whose names must all exist),
    and every ``.yxmc`` in the project, selected or not. From an upload: the
    uploaded files, and the ``.yxmc`` among them plus any sent as ``macros``.
    Sending uploads together with a ``project_id`` is rejected rather than ignored.
    """
    if not project_id:
        uploaded = await validate_and_read_files(files)
        extra = await _uploaded_macros(macros or [])
        return RunInputs(files=uploaded, macros=macro_files(uploaded) + extra)
    if any(getattr(f, "filename", None) for f in [*files, *(macros or [])]):
        raise HTTPException(status_code=422, detail="Send either uploaded files or a project_id, not both.")
    stored = await _project_files(project_id)
    library = macro_files(stored)
    if only is not None:
        names = {name for name, _ in stored}
        unknown = sorted(only - names)
        if unknown:
            raise HTTPException(status_code=422, detail=f"Not in this project: {', '.join(unknown)}")
        stored = [(name, content) for name, content in stored if name in only]
    if not stored:
        raise HTTPException(status_code=422, detail="This project has no workflows to analyze yet.")
    _enforce_limits(stored)
    return RunInputs(files=stored, macros=library)


async def resolve_input_files(
    files: list[UploadFile],
    project_id: str | None,
    *,
    only: set[str] | None = None,
) -> list[tuple[str, bytes]]:
    """Return ``[(file_name, bytes)]`` from the project when ``project_id`` is
    given, otherwise from the uploaded files. (Estate passes read every file, so
    the macros are among them; see :func:`resolve_run_inputs` for a run on part
    of a project.)
    """
    return (await resolve_run_inputs(files, project_id, only=only)).files


async def resolve_one_workflow(
    file: UploadFile | None,
    project_id: str | None,
    workflow_id: str | None,
    macros: list[UploadFile] | None = None,
) -> OneWorkflow:
    """One workflow from a project (``project_id`` + ``workflow_id``) or an upload
    (``file``, with any ``.yxmc`` it calls in ``macros``), and its macros."""
    if project_id or workflow_id:
        if (file is not None and file.filename) or any(getattr(m, "filename", None) for m in macros or []):
            raise HTTPException(status_code=422, detail="Send either a file or project_id + workflow_id, not both.")
        if not (project_id and workflow_id):
            raise HTTPException(status_code=422, detail="Pass both project_id and workflow_id.")
        require_projects()
        check_project_id(project_id)
        check_project_id(workflow_id)
        stored = await run_in_threadpool(project_service.get_workflow_with_macros, project_id, workflow_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="Unknown project or workflow.")
        (name, content), library = stored
        return OneWorkflow(name=name, content=content, macros=library)
    if file is None or not file.filename:
        raise HTTPException(status_code=422, detail="Upload a workflow, or pass project_id and workflow_id.")
    validate_yxmd_file(file)
    content = await read_upload(file)
    return OneWorkflow(name=file.filename, content=content, macros=await _uploaded_macros(macros or []))
