"""Batch orchestration with error accumulation and per-file metrics."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from a2d.config import ConversionConfig
from a2d.observability.errors import ConversionError, ErrorKind, ErrorSeverity
from a2d.observability.metrics import BatchMetrics, FileMetrics
from a2d.pipeline import (
    ConversionPipeline,
    ConversionResult,
    FormatConversionResult,
    MultiFormatConversionResult,
)

logger = logging.getLogger("a2d.observability.batch")

ProgressCallback = Callable[[int, int, str], None]


@dataclass
class FileConversionResult:
    """Outcome of converting a single file within a batch."""

    file_path: str
    workflow_name: str
    success: bool
    conversion_result: ConversionResult | None = None
    errors: list[ConversionError] = field(default_factory=list)
    metrics: FileMetrics = field(default_factory=FileMetrics)


@dataclass
class BatchConversionResult:
    """Outcome of converting a batch of files."""

    file_results: list[FileConversionResult] = field(default_factory=list)
    batch_metrics: BatchMetrics = field(default_factory=BatchMetrics)

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.file_results if r.success and not r.errors)

    @property
    def failure_count(self) -> int:
        return sum(1 for r in self.file_results if not r.success)

    @property
    def partial_count(self) -> int:
        return sum(1 for r in self.file_results if r.success and r.errors)

    def errors_by_kind(self) -> dict[ErrorKind, list[ConversionError]]:
        """Group all errors across files by their ErrorKind."""
        result: dict[ErrorKind, list[ConversionError]] = {}
        for fr in self.file_results:
            for err in fr.errors:
                result.setdefault(err.kind, []).append(err)
        return result

    def errors_by_severity(self) -> dict[ErrorSeverity, list[ConversionError]]:
        """Group all errors across files by their ErrorSeverity."""
        result: dict[ErrorSeverity, list[ConversionError]] = {}
        for fr in self.file_results:
            for err in fr.errors:
                result.setdefault(err.severity, []).append(err)
        return result


@dataclass
class MultiFormatFileResult:
    """Outcome of running all 4 generators against a single file.

    ``multi_result`` is None and ``parse_error`` is populated when the parse
    or DAG-build crashed before any generator ran. Otherwise ``multi_result``
    holds the per-format outcomes (one or more may still have ``status="failed"``).
    """

    file_path: str
    workflow_name: str
    multi_result: MultiFormatConversionResult | None
    metrics: FileMetrics = field(default_factory=FileMetrics)
    parse_error: ConversionError | None = None

    @property
    def success(self) -> bool:
        """True if at least one format produced output."""
        if self.multi_result is None:
            return False
        return any(fr.status == "success" for fr in self.multi_result.formats.values())

    def format_status(self, fmt_key: str) -> str:
        """Return ``"success"``/``"failed"``/``"missing"`` for one format."""
        if self.multi_result is None:
            return "missing"
        fr = self.multi_result.formats.get(fmt_key)
        return fr.status if fr is not None else "missing"


@dataclass
class MultiFormatBatchResult:
    """Batch outcome where every file produced all 4 formats in one parse."""

    file_results: list[MultiFormatFileResult] = field(default_factory=list)
    batch_metrics: BatchMetrics = field(default_factory=BatchMetrics)

    def per_format_success_counts(self) -> dict[str, int]:
        """Map each format id → count of files where that format succeeded."""
        counts: dict[str, int] = {
            "pyspark": 0,
            "dlt": 0,
            "sql": 0,
            "lakeflow": 0,
        }
        for fr in self.file_results:
            if fr.multi_result is None:
                continue
            for fmt_key, fmt_res in fr.multi_result.formats.items():
                if fmt_res.status == "success":
                    counts[fmt_key] = counts.get(fmt_key, 0) + 1
        return counts


def _classify_exception(exc: Exception) -> ErrorKind:
    """Classify an exception into an ErrorKind based on type/message heuristics."""
    exc_type = type(exc).__name__
    msg = str(exc).lower()

    if "parse" in exc_type.lower() or "xml" in msg or "lxml" in msg:
        return ErrorKind.PARSING
    if "convert" in exc_type.lower() or "converter" in msg or "unsupported" in msg:
        return ErrorKind.CONVERSION
    if "generat" in exc_type.lower() or "template" in msg or "jinja" in msg:
        return ErrorKind.GENERATION
    if isinstance(exc, OSError | FileNotFoundError | PermissionError):
        return ErrorKind.IO
    return ErrorKind.INTERNAL


class BatchOrchestrator:
    """Orchestrates batch conversion with error accumulation and metrics."""

    def __init__(self, config: ConversionConfig) -> None:
        self.config = config
        self.pipeline = ConversionPipeline(config)

    def convert_batch(
        self,
        file_paths: list[Path],
        progress_callback: ProgressCallback | None = None,
    ) -> BatchConversionResult:
        """Convert multiple files, accumulating errors instead of raising."""
        batch_start = datetime.now(timezone.utc)
        file_results: list[FileConversionResult] = []

        total = len(file_paths)
        for idx, path in enumerate(file_paths):
            if progress_callback:
                progress_callback(idx + 1, total, path.name)

            file_result = self._convert_single_with_tracking(path)
            file_results.append(file_result)

        batch_end = datetime.now(timezone.utc)

        batch_metrics = self._compute_batch_metrics(file_results, batch_start, batch_end)

        return BatchConversionResult(
            file_results=file_results,
            batch_metrics=batch_metrics,
        )

    def _convert_single_with_tracking(self, path: Path) -> FileConversionResult:
        """Convert a single file with error trapping and metrics population."""
        file_start = datetime.now(timezone.utc)
        file_path_str = str(path)
        workflow_name = path.stem
        errors: list[ConversionError] = []

        try:
            result = self.pipeline.convert(path)

            # Collect warnings as INFO-severity errors
            for warning in result.warnings:
                errors.append(
                    ConversionError(
                        kind=ErrorKind.CONVERSION,
                        severity=ErrorSeverity.WARNING,
                        message=warning,
                        file_path=file_path_str,
                    )
                )

            file_end = datetime.now(timezone.utc)
            stats = result.output.stats

            total_nodes = stats.get("total_nodes", result.dag.node_count)
            supported_nodes = stats.get("supported_nodes", total_nodes)
            unsupported_nodes = total_nodes - supported_nodes
            coverage = (supported_nodes / total_nodes * 100) if total_nodes > 0 else 100.0

            metrics = FileMetrics(
                file_path=file_path_str,
                workflow_name=workflow_name,
                started_at=file_start,
                completed_at=file_end,
                duration_seconds=(file_end - file_start).total_seconds(),
                node_count=result.dag.node_count,
                edge_count=result.dag.edge_count,
                supported_node_count=supported_nodes,
                unsupported_node_count=unsupported_nodes,
                coverage_percentage=coverage,
                files_generated=len(result.output.files),
                success=True,
            )

            return FileConversionResult(
                file_path=file_path_str,
                workflow_name=workflow_name,
                success=True,
                conversion_result=result,
                errors=errors,
                metrics=metrics,
            )

        except Exception as exc:
            logger.exception("Failed to convert %s", path)
            file_end = datetime.now(timezone.utc)

            error = ConversionError.from_exception(
                exc,
                _classify_exception(exc),
                file_path=file_path_str,
            )
            errors.append(error)

            metrics = FileMetrics(
                file_path=file_path_str,
                workflow_name=workflow_name,
                started_at=file_start,
                completed_at=file_end,
                duration_seconds=(file_end - file_start).total_seconds(),
                success=False,
            )

            return FileConversionResult(
                file_path=file_path_str,
                workflow_name=workflow_name,
                success=False,
                errors=errors,
                metrics=metrics,
            )

    # ── Multi-format path (incremental — does not replace convert_batch) ──
    #
    # The single-format ``convert_batch`` calls ``pipeline.convert(path)`` and
    # produces one ``ConversionResult`` per file. The multi-format path below
    # calls ``pipeline.convert_all_formats(path)`` so each file produces ALL
    # four formats in a single parse — matching ``server/services/batch.py``.
    # Both paths coexist so existing tests / single-format consumers don't
    # break.

    def convert_batch_multi_format(
        self,
        file_paths: list[Path],
        progress_callback: ProgressCallback | None = None,
    ) -> MultiFormatBatchResult:
        """Convert multiple files into all 4 formats per file.

        Returns ``MultiFormatBatchResult`` whose ``file_results`` carry a
        ``MultiFormatConversionResult`` reference plus per-format outcomes.
        Per-file failures (parser/DAG-build crashes) are captured as
        ``MultiFormatFileResult`` with ``parse_error`` populated.
        """
        batch_start = datetime.now(timezone.utc)
        file_results: list[MultiFormatFileResult] = []

        total = len(file_paths)
        for idx, path in enumerate(file_paths):
            if progress_callback:
                progress_callback(idx + 1, total, path.name)

            file_results.append(self._convert_single_multi_format(path))

        batch_end = datetime.now(timezone.utc)
        batch_metrics = self._compute_multi_batch_metrics(file_results, batch_start, batch_end)
        return MultiFormatBatchResult(file_results=file_results, batch_metrics=batch_metrics)

    def _convert_single_multi_format(self, path: Path) -> MultiFormatFileResult:
        """Run all 4 generators for a single file, capturing per-file failures."""
        file_start = datetime.now(timezone.utc)
        file_path_str = str(path)
        workflow_name = path.stem

        try:
            multi = self.pipeline.convert_all_formats(path)
        except Exception as exc:
            logger.exception("Failed to parse / build DAG for %s", path)
            file_end = datetime.now(timezone.utc)
            err = ConversionError.from_exception(exc, _classify_exception(exc), file_path=file_path_str)
            metrics = FileMetrics(
                file_path=file_path_str,
                workflow_name=workflow_name,
                started_at=file_start,
                completed_at=file_end,
                duration_seconds=(file_end - file_start).total_seconds(),
                success=False,
            )
            return MultiFormatFileResult(
                file_path=file_path_str,
                workflow_name=workflow_name,
                multi_result=None,
                metrics=metrics,
                parse_error=err,
            )

        # Aggregate metrics from the best successful format (mirrors the CLI's
        # ``_compute_top_coverage`` logic — coverage is format-agnostic in
        # practice but we read whichever successful generator we have).
        best_fr: FormatConversionResult | None = None
        for fmt_key in ("pyspark", "dlt", "sql", "lakeflow"):
            fr = multi.formats.get(fmt_key)
            if fr is not None and fr.status == "success" and fr.output is not None:
                best_fr = fr
                break

        if best_fr is not None and best_fr.output is not None:
            stats = best_fr.output.stats
            total_nodes = stats.get("total_nodes", multi.dag.node_count)
            supported_nodes = stats.get("supported_nodes", total_nodes)
            unsupported_nodes = total_nodes - supported_nodes
            coverage = (supported_nodes / total_nodes * 100) if total_nodes > 0 else 100.0
            files_generated = sum(
                len(fr.output.files)
                for fr in multi.formats.values()
                if fr.status == "success" and fr.output is not None
            )
        else:
            total_nodes = multi.dag.node_count
            supported_nodes = 0
            unsupported_nodes = total_nodes
            coverage = 0.0
            files_generated = 0

        file_end = datetime.now(timezone.utc)
        metrics = FileMetrics(
            file_path=file_path_str,
            workflow_name=workflow_name,
            started_at=file_start,
            completed_at=file_end,
            duration_seconds=(file_end - file_start).total_seconds(),
            node_count=multi.dag.node_count,
            edge_count=multi.dag.edge_count,
            supported_node_count=supported_nodes,
            unsupported_node_count=unsupported_nodes,
            coverage_percentage=coverage,
            files_generated=files_generated,
            # success at the file level = ANY format succeeded
            success=any(fr.status == "success" for fr in multi.formats.values()),
        )

        return MultiFormatFileResult(
            file_path=file_path_str,
            workflow_name=workflow_name,
            multi_result=multi,
            metrics=metrics,
            parse_error=None,
        )

    def _compute_multi_batch_metrics(
        self,
        file_results: list[MultiFormatFileResult],
        batch_start: datetime,
        batch_end: datetime,
    ) -> BatchMetrics:
        """Aggregate batch metrics for the multi-format path.

        ``successful_files`` = ALL 4 formats succeeded for that file.
        ``partial_files``    = at least one format succeeded but not all.
        ``failed_files``     = parse error OR every format failed.
        """
        total_files = len(file_results)
        successful = 0
        failed = 0
        partial = 0
        total_nodes = 0
        total_errors = 0
        total_warnings = 0
        coverages: list[float] = []

        for fr in file_results:
            if fr.parse_error is not None:
                failed += 1
                total_errors += 1
                continue
            assert fr.multi_result is not None  # guaranteed by parse_error branch
            fmt_succ = sum(1 for f in fr.multi_result.formats.values() if f.status == "success")
            fmt_fail = sum(1 for f in fr.multi_result.formats.values() if f.status == "failed")
            total_errors += fmt_fail
            total_warnings += sum(len(f.warnings) for f in fr.multi_result.formats.values())
            total_warnings += len(fr.multi_result.warnings)
            total_nodes += fr.multi_result.dag.node_count

            if fmt_succ == 0:
                failed += 1
            elif fmt_fail == 0:
                successful += 1
                coverages.append(fr.metrics.coverage_percentage)
            else:
                partial += 1
                coverages.append(fr.metrics.coverage_percentage)

        avg_coverage = sum(coverages) / len(coverages) if coverages else 0.0

        return BatchMetrics(
            started_at=batch_start,
            completed_at=batch_end,
            duration_seconds=(batch_end - batch_start).total_seconds(),
            total_files=total_files,
            successful_files=successful,
            failed_files=failed,
            partial_files=partial,
            total_nodes=total_nodes,
            total_errors=total_errors,
            total_warnings=total_warnings,
            avg_coverage_percentage=avg_coverage,
        )

    def _compute_batch_metrics(
        self,
        file_results: list[FileConversionResult],
        batch_start: datetime,
        batch_end: datetime,
    ) -> BatchMetrics:
        """Compute aggregate metrics from individual file results."""
        total_files = len(file_results)
        successful = sum(
            1 for r in file_results if r.success and not any(e.severity == ErrorSeverity.ERROR for e in r.errors)
        )
        failed = sum(1 for r in file_results if not r.success)
        partial = total_files - successful - failed

        total_nodes = sum(r.metrics.node_count for r in file_results)

        all_errors = [e for r in file_results for e in r.errors if e.severity == ErrorSeverity.ERROR]
        all_warnings = [e for r in file_results for e in r.errors if e.severity == ErrorSeverity.WARNING]

        coverages = [r.metrics.coverage_percentage for r in file_results if r.success]
        avg_coverage = sum(coverages) / len(coverages) if coverages else 0.0

        return BatchMetrics(
            started_at=batch_start,
            completed_at=batch_end,
            duration_seconds=(batch_end - batch_start).total_seconds(),
            total_files=total_files,
            successful_files=successful,
            failed_files=failed,
            partial_files=partial,
            total_nodes=total_nodes,
            total_errors=len(all_errors),
            total_warnings=len(all_warnings),
            avg_coverage_percentage=avg_coverage,
        )
