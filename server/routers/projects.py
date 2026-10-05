"""Migration Project endpoints — the durable estate behind the whole app.

Read/write a project: create it with an estate of workflows (stored once), list
and fetch projects, add workflows, fetch a stored workflow's bytes (so any screen
operates on it without a re-upload), and advance a workflow's lifecycle stage.

Projects are optional. When no database is configured the service is unavailable
and these endpoints return 503 with a clear message, so the client falls back to
its in-session stores — the app behaves exactly as it does today. See
``docs/migration-project-design.md``.
"""

from __future__ import annotations

import io
import logging

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from server.services import project as project_service
from server.utils.validation import validate_and_read_files

logger = logging.getLogger("a2d.server.routers.projects")

router = APIRouter(prefix="/api/projects", tags=["projects"])

_UNAVAILABLE = (
    "Migration projects require a database backend, which is not configured. "
    "Set up Postgres/Lakebase (see the deployment docs) to persist a project; "
    "without it the app still works per-visit without saved projects."
)


def _require_available() -> None:
    if not project_service.is_available():
        raise HTTPException(status_code=503, detail=_UNAVAILABLE)


@router.get("")
async def list_projects(limit: int = 50, offset: int = 0) -> dict:
    """List saved projects (summary + rollups)."""
    _require_available()
    items, total = project_service.list_projects(limit=limit, offset=offset)
    return {"projects": items, "total": total}


@router.post("")
async def create_project(
    files: list[UploadFile] = File(...),
    name: str = Form("Untitled migration"),
) -> dict:
    """Create a project from an uploaded estate (files stored once)."""
    _require_available()
    file_data = await validate_and_read_files(files)
    project = project_service.create_project(name, file_data)
    if project is None:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE)
    logger.info("Created project %s with %d workflow(s)", project["id"], len(file_data))
    return project


@router.get("/{project_id}")
async def get_project(project_id: str) -> dict:
    """Fetch a project with its workflows, stages, and rollups."""
    _require_available()
    project = project_service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Unknown project {project_id!r}")
    return project


@router.post("/{project_id}/workflows")
async def add_workflows(project_id: str, files: list[UploadFile] = File(...)) -> dict:
    """Add workflows to an existing project."""
    _require_available()
    file_data = await validate_and_read_files(files)
    project = project_service.add_workflows(project_id, file_data)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Unknown project {project_id!r}")
    return project


@router.get("/{project_id}/workflows/{workflow_id}/file")
async def get_workflow_file(project_id: str, workflow_id: str) -> StreamingResponse:
    """Return a stored workflow's bytes, so a screen reads it without re-upload."""
    _require_available()
    result = project_service.get_workflow_file(project_id, workflow_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown project or workflow")
    file_name, content = result
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


@router.patch("/{project_id}/workflows/{workflow_id}")
async def update_workflow(project_id: str, workflow_id: str, payload: dict = Body(...)) -> dict:
    """Advance a workflow's lifecycle stage (and optionally store its artifact)."""
    _require_available()
    stage = payload.get("stage")
    if not isinstance(stage, str):
        raise HTTPException(status_code=400, detail="'stage' (string) is required")
    artifact_key = payload.get("artifact_key")
    artifact = payload.get("artifact")
    try:
        ok = project_service.set_workflow_stage(
            project_id, workflow_id, stage, artifact_key=artifact_key, artifact=artifact
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    if not ok:
        raise HTTPException(status_code=404, detail="Unknown project or workflow")
    return project_service.get_project(project_id) or {}


@router.delete("/{project_id}")
async def delete_project(project_id: str) -> dict:
    """Delete a project and its stored workflows."""
    _require_available()
    if not project_service.delete_project(project_id):
        raise HTTPException(status_code=404, detail=f"Unknown project {project_id!r}")
    return {"deleted": project_id}
