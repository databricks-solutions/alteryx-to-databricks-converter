"""Batch conversion service — multi-format async job tracking.

Bypasses ``BatchOrchestrator`` for the server path: per-file calls into
``ConversionPipeline.convert_all_formats`` are made directly so each file's
result contains ``formats: {pyspark, dlt, sql, lakeflow}``. The CLI continues
to use ``BatchOrchestrator`` for its single-format workflow.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from a2d.config import ConversionConfig, OutputFormat
from a2d.pipeline import ConversionPipeline, MultiFormatConversionResult
from server.services.conversion import (
    _serialize_dag,
    _serialize_format_result,
    generate_ddl_dab_files,
)
from server.settings import settings
from server.utils.validation import sanitize_filename

logger = logging.getLogger("a2d.server.services.batch")


class JobStatus(str, Enum):
    """Status of a batch conversion job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class BatchJob:
    job_id: str
    status: JobStatus = JobStatus.PENDING
    progress: int = 0
    total: int = 0
    current_filename: str = ""
    file_results: list[dict] = field(default_factory=list)
    batch_metrics: dict | None = None
    errors_by_kind: dict[str, int] | None = None
    error_message: str | None = None
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    created_at: float = field(default_factory=time.monotonic)
    task: asyncio.Task | None = None


class JobStore:
    """Thread-safe in-memory store for batch jobs."""

    def __init__(self) -> None:
        self._jobs: dict[str, BatchJob] = {}
        self._lock = threading.Lock()

    def get(self, job_id: str) -> BatchJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def create(self, total: int) -> BatchJob:
        job_id = uuid.uuid4().hex[:12]
        job = BatchJob(job_id=job_id, total=total)
        with self._lock:
            self._jobs[job_id] = job
        return job

    def subscribe(self, job_id: str, queue: asyncio.Queue) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            job.subscribers.append(queue)
            return True

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job and queue in job.subscribers:
                job.subscribers.remove(queue)

    def evict_expired(self) -> int:
        """Remove jobs older than the configured TTL. Returns count of evicted jobs."""
        now = time.monotonic()
        expired_jobs: list[BatchJob] = []
        with self._lock:
            expired_ids = [jid for jid, job in self._jobs.items() if now - job.created_at > settings.job_ttl_seconds]
            for jid in expired_ids:
                expired_jobs.append(self._jobs.pop(jid))
        # Cancel running tasks and notify lingering subscribers outside the lock
        for job in expired_jobs:
            if job.task and not job.task.done():
                job.task.cancel()
            for q in job.subscribers:
                with contextlib.suppress(Exception):
                    q.put_nowait({"type": "job_expired", "message": "Job expired"})
        return len(expired_jobs)


_store = JobStore()


def get_store() -> JobStore:
    """Return the global job store (for use in lifespan cleanup)."""
    return _store


def get_job(job_id: str) -> BatchJob | None:
    return _store.get(job_id)


async def create_batch_job(
    files: list[tuple[str, bytes]],
    *,
    catalog_name: str = "main",
    schema_name: str = "default",
    include_comments: bool = True,
    include_expression_audit: bool = False,
    include_performance_hints: bool = False,
    generate_ddl: bool = False,
    generate_dab: bool = False,
    expand_macros: bool = False,
) -> str:
    """Create a multi-format batch job and return job_id. Starts conversion in background."""
    job = _store.create(total=len(files))
    logger.info("Created batch job %s: %d files (multi-format)", job.job_id, len(files))
    job.task = asyncio.create_task(
        _run_batch(
            job,
            files,
            catalog_name=catalog_name,
            schema_name=schema_name,
            include_comments=include_comments,
            include_expression_audit=include_expression_audit,
            include_performance_hints=include_performance_hints,
            generate_ddl=generate_ddl,
            generate_dab=generate_dab,
            expand_macros=expand_macros,
        )
    )
    return job.job_id


def subscribe(job_id: str, queue: asyncio.Queue) -> bool:
    return _store.subscribe(job_id, queue)


def unsubscribe(job_id: str, queue: asyncio.Queue) -> None:
    _store.unsubscribe(job_id, queue)


def _convert_one(pipeline: ConversionPipeline, file_path: Path) -> MultiFormatConversionResult | Exception:
    """Run a single file conversion. Returns the result or the exception raised."""
    try:
        return pipeline.convert_all_formats(file_path)
    except Exception as exc:  # per-file isolation
        return exc


def _build_multi_file_result(
    file_path: Path,
    workflow_name: str,
    result: MultiFormatConversionResult | Exception,
    *,
    extra_files: list[dict] | None = None,
    extra_warnings: list[str] | None = None,
) -> dict:
    """Build a serializable dict for a single file's multi-format result.

    ``extra_files`` (DDL/DAB) are appended into every successful format so each
    download is self-contained, mirroring the single-file path.
    """
    file_name = file_path.name

    if isinstance(result, Exception):
        # Hard failure: parse/DAG build crashed before any format ran
        return {
            "file_name": file_name,
            "workflow_name": workflow_name,
            "success": False,
            "coverage": 0.0,
            "node_count": 0,
            "edge_count": 0,
            "files_generated": 0,
            "errors": [
                {
                    "message": str(result),
                    "severity": "ERROR",
                    "tool_type": None,
                    "node_id": None,
                }
            ],
            "warnings": list(extra_warnings or []),
            "best_format": "",
            "formats": {},
            "dag_data": None,
        }

    formats_dict: dict[str, dict] = {}
    total_files = 0
    coverages: list[float] = []
    any_success = False
    all_warnings: list[str] = list(result.warnings)
    if extra_warnings:
        all_warnings.extend(extra_warnings)
    error_dicts: list[dict] = []

    for fmt_key, fr in result.formats.items():
        serialized = _serialize_format_result(fr)
        if extra_files and fr.status == "success":
            serialized["files"] = serialized["files"] + extra_files
        formats_dict[fmt_key] = serialized
        if fr.status == "success" and fr.output is not None:
            any_success = True
            total_files += len(fr.output.files) + (len(extra_files) if extra_files else 0)
            # Read derived coverage from the serialized stats (set in
            # _serialize_format_result) — generators don't emit it directly.
            cov = serialized.get("stats", {}).get("coverage_percentage")
            if isinstance(cov, (int | float)):
                coverages.append(float(cov))
            all_warnings.extend(fr.warnings)
        elif fr.status == "failed":
            error_dicts.append(
                {
                    "message": f"[{fmt_key}] {fr.error or 'unknown error'}",
                    "severity": "ERROR",
                    "tool_type": None,
                    "node_id": None,
                }
            )

    avg_coverage = sum(coverages) / len(coverages) if coverages else 0.0

    return {
        "file_name": file_name,
        "workflow_name": workflow_name,
        "success": any_success,
        "coverage": avg_coverage,
        "node_count": result.dag.node_count,
        "edge_count": result.dag.edge_count,
        "files_generated": total_files,
        "errors": error_dicts,
        "warnings": all_warnings,
        "best_format": result.best_format,
        "formats": formats_dict,
        "dag_data": _serialize_dag(result.dag),
    }


async def _run_batch(
    job: BatchJob,
    files: list[tuple[str, bytes]],
    *,
    catalog_name: str = "main",
    schema_name: str = "default",
    include_comments: bool = True,
    include_expression_audit: bool = False,
    include_performance_hints: bool = False,
    generate_ddl: bool = False,
    generate_dab: bool = False,
    expand_macros: bool = False,
) -> None:
    """Run multi-format batch conversion in the background."""
    job.status = JobStatus.RUNNING
    logger.info("Batch job %s started", job.job_id)

    started_at = time.monotonic()

    try:
        # OutputFormat.PYSPARK is a placeholder — convert_all_formats ignores it.
        config = ConversionConfig(
            input_path=Path("."),
            output_format=OutputFormat.PYSPARK,
            generate_orchestration=True,
            catalog_name=catalog_name,
            schema_name=schema_name,
            include_comments=include_comments,
            include_expression_audit=include_expression_audit,
            include_performance_hints=include_performance_hints,
            expand_macros=expand_macros,
        )
        pipeline = ConversionPipeline(config)

        with tempfile.TemporaryDirectory() as tmpdir:
            file_paths: list[tuple[str, Path]] = []
            for original_filename, content in files:
                p = Path(tmpdir) / sanitize_filename(original_filename)
                p.write_bytes(content)
                file_paths.append((original_filename, p))

            total_files = len(file_paths)
            successful_files = 0
            failed_files = 0
            partial_files = 0
            total_nodes = 0
            total_errors = 0
            total_warnings = 0
            errors_by_kind: dict[str, int] = {}

            for idx, (original_filename, fp) in enumerate(file_paths, start=1):
                workflow_name = fp.stem
                job.current_filename = original_filename

                # Run the multi-format conversion in a thread (CPU-bound)
                outcome = await asyncio.to_thread(_convert_one, pipeline, fp)

                # DDL/DAB generation (per-file, mirrors single-file path)
                extra_files: list[dict] = []
                ddl_dab_warnings: list[str] = []
                if not isinstance(outcome, Exception) and (generate_ddl or generate_dab):
                    extra_files, ddl_dab_warnings = generate_ddl_dab_files(
                        config,
                        outcome,
                        workflow_name,
                        generate_ddl=generate_ddl,
                        generate_dab=generate_dab,
                    )

                file_result = _build_multi_file_result(
                    fp,
                    workflow_name,
                    outcome,
                    extra_files=extra_files,
                    extra_warnings=ddl_dab_warnings,
                )

                # Aggregate batch metrics
                if isinstance(outcome, Exception):
                    failed_files += 1
                    total_errors += 1
                    errors_by_kind["parse_error"] = errors_by_kind.get("parse_error", 0) + 1
                else:
                    fmt_failures = sum(1 for fr in outcome.formats.values() if fr.status == "failed")
                    fmt_successes = sum(1 for fr in outcome.formats.values() if fr.status == "success")
                    if fmt_failures == 0 and fmt_successes > 0:
                        successful_files += 1
                    elif fmt_successes > 0:
                        partial_files += 1
                    else:
                        failed_files += 1

                    if fmt_failures:
                        errors_by_kind["generator_failure"] = errors_by_kind.get("generator_failure", 0) + fmt_failures
                    total_errors += fmt_failures
                    total_nodes += outcome.dag.node_count
                    total_warnings += sum(len(fr.warnings) for fr in outcome.formats.values())
                    total_warnings += len(outcome.warnings)

                # Progress callback (per-file)
                job.progress = idx
                job.file_results.append(file_result)

                # Send lightweight WS message (drop heavy 'formats' payload)
                summary = {k: v for k, v in file_result.items() if k != "formats" and k != "dag_data"}
                summary["formats_summary"] = {
                    fmt_key: {
                        "status": fmt_result.get("status"),
                        "files": len(fmt_result.get("files", [])),
                    }
                    for fmt_key, fmt_result in (file_result.get("formats") or {}).items()
                }
                msg = {"type": "file_complete", **summary}
                for q in list(job.subscribers):
                    await q.put(msg)

        duration = time.monotonic() - started_at
        avg_coverage = 0.0
        successful_results = [fr for fr in job.file_results if fr.get("success") and fr.get("coverage") is not None]
        if successful_results:
            avg_coverage = sum(fr["coverage"] for fr in successful_results) / len(successful_results)

        job.batch_metrics = {
            "duration_seconds": duration,
            "total_files": total_files,
            "successful_files": successful_files,
            "failed_files": failed_files,
            "partial_files": partial_files,
            "total_nodes": total_nodes,
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "avg_coverage_percentage": avg_coverage,
        }
        job.errors_by_kind = errors_by_kind
        job.status = JobStatus.COMPLETED

        logger.info(
            "Batch job %s completed: %d files (%d ok, %d partial, %d failed)",
            job.job_id,
            total_files,
            successful_files,
            partial_files,
            failed_files,
        )

        complete_msg = {
            "type": "batch_complete",
            "batch_metrics": job.batch_metrics,
            "errors_by_kind": job.errors_by_kind,
            "file_results": [
                {k: v for k, v in fr.items() if k != "formats" and k != "dag_data"} for fr in job.file_results
            ],
        }
        for q in list(job.subscribers):
            await q.put(complete_msg)
    except Exception:
        logger.exception("Batch job %s failed", job.job_id)
        job.status = JobStatus.FAILED
        job.error_message = "Internal batch conversion error"
        error_msg = {"type": "error", "message": job.error_message}
        for q in list(job.subscribers):
            await q.put(error_msg)
