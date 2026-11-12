"""Migration Project endpoints: the durable estate behind the whole app.

Create a project with its workflows (stored once); list, fetch, rename and
delete projects; add workflows (re-adding a file name replaces that workflow,
identical bytes change nothing) or remove one; fetch a stored workflow's bytes;
and move a workflow's lifecycle stage forward.

Projects are optional. With no database configured these endpoints answer 503
"not configured" and the app keeps its project in the browser instead; with a
database that isn't responding they answer 503 "temporarily unavailable", so a
client can tell an outage from "no database". Projects are shared by everyone who
can open the app (the same tenancy as conversion history). See
``docs/migration-project-design.md``.

The database driver is synchronous, so every store call runs in a worker thread
rather than on the event loop.
"""

from __future__ import annotations

import io
import logging

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from server.services import project as project_service
from server.utils.headers import content_disposition
from server.utils.project_input import check_project_id, require_projects
from server.utils.validation import validate_and_read_files

logger = logging.getLogger("a2d.server.routers.projects")

router = APIRouter(prefix="/api/projects", tags=["projects"])


async def _reread(project_id: str) -> dict:
    """The project after a change. A change that succeeded but can't be read back
    is reported as unavailable, not as an empty 200."""
    project = await run_in_threadpool(project_service.get_project, project_id)
    if project is None:
        raise HTTPException(status_code=503, detail="The change was saved, but the project couldn't be read back.")
    return project


@router.get("")
async def list_projects(limit: int = 50, offset: int = 0) -> dict:
    """List saved projects (summary + rollups)."""
    require_projects()
    items, total = await run_in_threadpool(project_service.list_projects, limit, offset)
    return {"projects": items, "total": total}


@router.post("")
async def create_project(
    files: list[UploadFile] = File(...),
    name: str = Form("Untitled migration"),
) -> dict:
    """Create a project from an uploaded estate (files stored once)."""
    require_projects()
    file_data = await validate_and_read_files(files)
    project = await run_in_threadpool(project_service.create_project, name, file_data)
    if project is None:
        require_projects()  # raises with the right message
        raise HTTPException(status_code=503, detail="The project couldn't be created.")
    logger.info("Created project %s with %d workflow(s)", project["id"], len(file_data))
    return project


@router.get("/{project_id}")
async def get_project(project_id: str) -> dict:
    """Fetch a project with its workflows, stages, and rollups."""
    require_projects()
    check_project_id(project_id)
    project = await run_in_threadpool(project_service.get_project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Unknown project {project_id!r}")
    return project


@router.patch("/{project_id}")
async def rename_project(project_id: str, payload: dict = Body(...)) -> dict:
    """Rename a project."""
    require_projects()
    check_project_id(project_id)
    name = payload.get("name")
    if not isinstance(name, str):
        raise HTTPException(status_code=422, detail="'name' (string) is required")
    try:
        ok = await run_in_threadpool(project_service.rename_project, project_id, name)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    if not ok:
        raise HTTPException(status_code=404, detail=f"Unknown project {project_id!r}")
    return await _reread(project_id)


@router.post("/{project_id}/workflows")
async def add_workflows(project_id: str, files: list[UploadFile] = File(...)) -> dict:
    """Add workflows to a project. A file whose name is already there replaces
    that workflow; identical bytes leave it as it is. The response's ``changes``
    says which happened to each file."""
    require_projects()
    check_project_id(project_id)
    file_data = await validate_and_read_files(files)
    project = await run_in_threadpool(project_service.add_workflows, project_id, file_data)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Unknown project {project_id!r}")
    return project


@router.get("/{project_id}/workflows/{workflow_id}/file")
async def get_workflow_file(project_id: str, workflow_id: str) -> StreamingResponse:
    """Return a stored workflow's bytes, so a step reads it without a re-upload."""
    require_projects()
    check_project_id(project_id)
    check_project_id(workflow_id)
    result = await run_in_threadpool(project_service.get_workflow_file, project_id, workflow_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown project or workflow")
    file_name, content = result
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/octet-stream",
        headers={"Content-Disposition": content_disposition(file_name)},
    )


@router.patch("/{project_id}/workflows/{workflow_id}")
async def update_workflow(project_id: str, workflow_id: str, payload: dict = Body(...)) -> dict:
    """Move a workflow's lifecycle stage forward (and optionally store its artifact)."""
    require_projects()
    check_project_id(project_id)
    check_project_id(workflow_id)
    stage = payload.get("stage")
    if not isinstance(stage, str):
        raise HTTPException(status_code=422, detail="'stage' (string) is required")
    artifact_key = payload.get("artifact_key")
    artifact = payload.get("artifact")
    if artifact_key is not None and not isinstance(artifact_key, str):
        raise HTTPException(status_code=422, detail="'artifact_key' must be a string")
    if artifact is not None and not isinstance(artifact, dict):
        raise HTTPException(status_code=422, detail="'artifact' must be an object")
    try:
        ok = await run_in_threadpool(
            lambda: project_service.set_workflow_stage(
                project_id, workflow_id, stage, artifact_key=artifact_key, artifact=artifact
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    if not ok:
        raise HTTPException(status_code=404, detail="Unknown project or workflow")
    return await _reread(project_id)


@router.delete("/{project_id}/workflows/{workflow_id}")
async def delete_workflow(project_id: str, workflow_id: str) -> dict:
    """Remove one workflow from a project."""
    require_projects()
    check_project_id(project_id)
    check_project_id(workflow_id)
    if not await run_in_threadpool(project_service.delete_workflow, project_id, workflow_id):
        raise HTTPException(status_code=404, detail="Unknown project or workflow")
    return await _reread(project_id)


@router.delete("/{project_id}")
async def delete_project(project_id: str) -> dict:
    """Delete a project and its stored workflows."""
    require_projects()
    check_project_id(project_id)
    if not await run_in_threadpool(project_service.delete_project, project_id):
        raise HTTPException(status_code=404, detail=f"Unknown project {project_id!r}")
    return {"deleted": project_id}
