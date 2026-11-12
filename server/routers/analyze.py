"""Analysis endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from server.models.responses import AnalysisResponse
from server.services import project as project_service
from server.services.analysis import analyze_files
from server.utils.deadline import run_with_timeout
from server.utils.project_input import resolve_input_files

logger = logging.getLogger("a2d.server.routers.analyze")

router = APIRouter(prefix="/api", tags=["analyze"])


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze(
    files: list[UploadFile] = File(default=[]),
    project_id: str | None = Form(None),
) -> AnalysisResponse:
    # Source the estate from a saved project when given, else from the upload.
    file_data = await resolve_input_files(files, project_id)

    logger.info("Analyzing %d workflow(s)%s", len(file_data), f" (project {project_id})" if project_id else "")
    try:
        result = await run_with_timeout(analyze_files, file_data, label=f"Analyzing {len(file_data)} workflow(s)")
    except ValueError as e:
        logger.warning("Validation error analyzing files: %s", e)
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error analyzing files")
        raise HTTPException(status_code=500, detail="Internal analysis error")

    # Reflect that the estate's freshly-uploaded workflows have now been assessed.
    if project_id:
        # Keep each analyzed workflow's summary on the project (feeds the coverage
        # rollup) and move it to "assessed", but only if it still holds the bytes
        # that were analyzed. Skipped files stay where they are.
        hashes = {name: project_service.content_hash(content) for name, content in file_data}
        analyzed = [w.get("source_file_name") or w["file_name"] for w in result.get("workflows", [])]
        await run_in_threadpool(project_service.store_analysis, project_id, result.get("workflows", []), hashes)
        await run_in_threadpool(project_service.advance_workflows_by_name, project_id, analyzed, "assessed", hashes)

    logger.info("Analysis complete: %d workflows", len(file_data))
    return AnalysisResponse(**result)
