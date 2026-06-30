"""Outcome report generation for batch conversion results."""

from __future__ import annotations

import html
import json
from pathlib import Path

from a2d.observability.batch import (
    BatchConversionResult,
    FileConversionResult,
    MultiFormatBatchResult,
    MultiFormatFileResult,
)
from a2d.observability.errors import ErrorKind, ErrorSeverity
from a2d.observability.hints import enrich_warnings

_FORMAT_KEYS: tuple[str, ...] = ("pyspark", "dlt", "sql", "lakeflow")
_FORMAT_LABELS: dict[str, str] = {
    "pyspark": "PySpark",
    "dlt": "Spark Declarative Pipelines",
    "sql": "Spark SQL",
    "lakeflow": "Lakeflow Designer",
}


class OutcomeReportGenerator:
    """Generate outcome reports in JSON, JSONL, and HTML formats."""

    def generate_json(self, result: BatchConversionResult, output_path: Path) -> None:
        """Write a comprehensive JSON report."""
        report = {
            "batch_metrics": result.batch_metrics.to_dict(),
            "file_results": [self._serialize_file_result(fr) for fr in result.file_results],
            "error_summary": self._error_summary(result),
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, default=str))

    def generate_jsonl(self, result: BatchConversionResult, output_path: Path) -> None:
        """Write a streaming JSONL report (one record per line)."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []

        # Batch start record
        lines.append(
            json.dumps(
                {"type": "batch_start", "data": result.batch_metrics.to_dict()},
                default=str,
            )
        )

        # Per-file records
        for fr in result.file_results:
            lines.append(
                json.dumps(
                    {
                        "type": "file_result",
                        "data": {
                            "file_path": fr.file_path,
                            "workflow_name": fr.workflow_name,
                            "success": fr.success,
                            "metrics": fr.metrics.to_dict(),
                        },
                    },
                    default=str,
                )
            )

        # Error records
        for fr in result.file_results:
            for err in fr.errors:
                lines.append(json.dumps({"type": "error", "data": err.to_dict()}, default=str))

        output_path.write_text("\n".join(lines) + "\n")

    def generate_html(self, result: BatchConversionResult, output_path: Path) -> None:
        """Write an HTML outcome report with status table, confidence, and error breakdown."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        bm = result.batch_metrics

        # Build file results table rows
        rows = ""
        for fr in result.file_results:
            status_class = "success" if fr.success else "failure"
            status_icon = "&#9989;" if fr.success else "&#10060;"
            error_count = sum(1 for e in fr.errors if e.severity == ErrorSeverity.ERROR)
            warning_count = sum(1 for e in fr.errors if e.severity == ErrorSeverity.WARNING)

            # Confidence info
            confidence_cell = "-"
            if fr.conversion_result and fr.conversion_result.confidence:
                c = fr.conversion_result.confidence
                color = {"High": "#28a745", "Medium": "#e6a700", "Low": "#dc3545"}.get(c.level, "#999")
                confidence_cell = f'<span style="color:{color};font-weight:600">{c.overall:.0f} ({c.level})</span>'

            rows += (
                f"<tr class='{status_class}'>"
                f"<td>{status_icon}</td>"
                f"<td>{html.escape(fr.workflow_name)}</td>"
                f"<td>{fr.metrics.coverage_percentage:.0f}%</td>"
                f"<td>{confidence_cell}</td>"
                f"<td>{error_count}</td>"
                f"<td>{warning_count}</td>"
                f"<td>{fr.metrics.duration_seconds:.2f}s</td>"
                f"</tr>"
            )

        # Error breakdown by kind
        errors_by_kind = result.errors_by_kind()
        error_breakdown_rows = ""
        for kind in ErrorKind:
            count = len(errors_by_kind.get(kind, []))
            if count > 0:
                error_breakdown_rows += f"<tr><td>{kind.value}</td><td>{count}</td></tr>"

        # Enriched warnings with hints
        all_warnings = []
        for fr in result.file_results:
            if fr.conversion_result:
                all_warnings.extend(fr.conversion_result.warnings)
        enriched = enrich_warnings(all_warnings)
        hint_rows = ""
        for item in enriched:
            if item["hint"]:
                hint_rows += (
                    f"<tr>"
                    f"<td>{html.escape(item['message'][:120])}</td>"
                    f"<td><strong>{html.escape(item['hint'])}</strong></td>"
                    f"<td>{html.escape(item['category'] or '')}</td>"
                    f"</tr>"
                )

        hints_section = ""
        if hint_rows:
            hints_section = f"""
<h2>Actionable Recommendations</h2>
<table>
<thead><tr><th>Warning</th><th>Next Step</th><th>Category</th></tr></thead>
<tbody>{hint_rows}</tbody>
</table>"""

        html_content = f"""<!DOCTYPE html>
<html>
<head>
<title>a2d Batch Conversion Report</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 2rem; }}
h1 {{ color: #1b3a57; }}
h2 {{ color: #2d6a9f; margin-top: 2rem; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #f2f2f2; }}
tr.success {{ background: #f0fff0; }}
tr.failure {{ background: #fff0f0; }}
.metrics {{ display: flex; gap: 2rem; margin: 1rem 0; flex-wrap: wrap; }}
.metric {{ background: #f8f9fb; border-radius: 8px; padding: 1rem 1.5rem; text-align: center; }}
.metric .value {{ font-size: 1.5rem; font-weight: bold; }}
.metric .label {{ font-size: 0.85rem; color: #666; }}
</style>
</head>
<body>
<h1>a2d Batch Conversion Report</h1>

<div class="metrics">
<div class="metric"><div class="value">{bm.total_files}</div><div class="label">Total Files</div></div>
<div class="metric"><div class="value">{bm.successful_files}</div><div class="label">Successful</div></div>
<div class="metric"><div class="value">{bm.partial_files}</div><div class="label">Partial</div></div>
<div class="metric"><div class="value">{bm.failed_files}</div><div class="label">Failed</div></div>
<div class="metric"><div class="value">{bm.duration_seconds:.2f}s</div><div class="label">Duration</div></div>
<div class="metric"><div class="value">{bm.avg_coverage_percentage:.0f}%</div><div class="label">Avg Coverage</div></div>
</div>

<h2>File Results</h2>
<table>
<thead><tr><th>Status</th><th>Workflow</th><th>Coverage</th><th>Confidence</th><th>Errors</th><th>Warnings</th><th>Duration</th></tr></thead>
<tbody>{rows}</tbody>
</table>

<h2>Error Breakdown by Stage</h2>
<table>
<thead><tr><th>Stage</th><th>Count</th></tr></thead>
<tbody>{error_breakdown_rows if error_breakdown_rows else "<tr><td colspan='2'>No errors</td></tr>"}</tbody>
</table>

{hints_section}

</body>
</html>"""

        output_path.write_text(html_content)

    def _serialize_file_result(self, fr: FileConversionResult) -> dict:
        """Serialize a single file result for JSON output, including confidence and hints."""
        data: dict = {
            "file_path": fr.file_path,
            "workflow_name": fr.workflow_name,
            "success": fr.success,
            "metrics": fr.metrics.to_dict(),
            "errors": [e.to_dict() for e in fr.errors],
        }

        # Add confidence if available
        if fr.conversion_result and fr.conversion_result.confidence:
            data["confidence"] = fr.conversion_result.confidence.to_dict()

        # Add enriched warnings with hints
        if fr.conversion_result and fr.conversion_result.warnings:
            data["enriched_warnings"] = enrich_warnings(fr.conversion_result.warnings)

        return data

    def _error_summary(self, result: BatchConversionResult) -> dict:
        """Build an error summary dict for the JSON report."""
        by_kind: dict[str, int] = {}
        by_severity: dict[str, int] = {}

        for fr in result.file_results:
            for err in fr.errors:
                by_kind[err.kind.value] = by_kind.get(err.kind.value, 0) + 1
                by_severity[err.severity.value] = by_severity.get(err.severity.value, 0) + 1

        return {
            "by_kind": by_kind,
            "by_severity": by_severity,
            "total": sum(by_severity.values()),
        }

    # ── Multi-format reports ─────────────────────────────────────────────
    #
    # The single-format methods above continue to work unchanged. The
    # methods below render a ``MultiFormatBatchResult`` so each file shows
    # per-format columns (pyspark / dlt / sql / lakeflow). All three
    # report shapes (JSON, JSONL, HTML) are extended.

    def generate_json_multi(self, result: MultiFormatBatchResult, output_path: Path) -> None:
        """Write a JSON report with per-format outcomes per file."""
        report = {
            "batch_metrics": result.batch_metrics.to_dict(),
            "per_format_success_counts": result.per_format_success_counts(),
            "file_results": [self._serialize_multi_file_result(fr) for fr in result.file_results],
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, default=str))

    def generate_jsonl_multi(self, result: MultiFormatBatchResult, output_path: Path) -> None:
        """Write a streaming JSONL report — one record per file/format event."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        lines.append(
            json.dumps(
                {"type": "batch_start", "data": result.batch_metrics.to_dict()},
                default=str,
            )
        )

        for fr in result.file_results:
            lines.append(
                json.dumps(
                    {
                        "type": "file_result",
                        "data": {
                            "file_path": fr.file_path,
                            "workflow_name": fr.workflow_name,
                            "success": fr.success,
                            "metrics": fr.metrics.to_dict(),
                            "format_status": {fmt: fr.format_status(fmt) for fmt in _FORMAT_KEYS},
                        },
                    },
                    default=str,
                )
            )
            if fr.parse_error is not None:
                lines.append(
                    json.dumps(
                        {"type": "error", "data": fr.parse_error.to_dict()},
                        default=str,
                    )
                )
            elif fr.multi_result is not None:
                for fmt_key, fmt_res in fr.multi_result.formats.items():
                    if fmt_res.status == "failed":
                        lines.append(
                            json.dumps(
                                {
                                    "type": "format_error",
                                    "data": {
                                        "file_path": fr.file_path,
                                        "format": fmt_key,
                                        "error": fmt_res.error,
                                    },
                                },
                                default=str,
                            )
                        )

        output_path.write_text("\n".join(lines) + "\n")

    def generate_html_multi(self, result: MultiFormatBatchResult, output_path: Path) -> None:
        """Write an HTML report with one column per format."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        bm = result.batch_metrics

        format_headers = "".join(f"<th>{html.escape(_FORMAT_LABELS[fmt])}</th>" for fmt in _FORMAT_KEYS)

        rows = ""
        for fr in result.file_results:
            status_class = "success" if fr.success else "failure"
            file_status_icon = "&#9989;" if fr.success else "&#10060;"
            best_fmt_html = ""
            if fr.multi_result is not None and fr.multi_result.best_format:
                best_fmt_html = (
                    f'<span style="color:#2d6a9f;font-weight:600">'
                    f"{html.escape(_FORMAT_LABELS.get(fr.multi_result.best_format, fr.multi_result.best_format))}"
                    f"</span>"
                )

            fmt_cells = ""
            for fmt in _FORMAT_KEYS:
                status = fr.format_status(fmt)
                if status == "success":
                    cell = '<span style="color:#28a745;font-weight:600">&#9989; OK</span>'
                    if fr.multi_result is not None:
                        fmt_res = fr.multi_result.formats.get(fmt)
                        if fmt_res is not None and fmt_res.duration_ms:
                            cell += (
                                f'<br><span style="font-size:0.85em;color:#666">'
                                f"{fmt_res.duration_ms / 1000:.2f}s</span>"
                            )
                elif status == "failed":
                    err_msg = ""
                    if fr.multi_result is not None:
                        fmt_res = fr.multi_result.formats.get(fmt)
                        if fmt_res is not None and fmt_res.error:
                            err_msg = html.escape(fmt_res.error[:40])
                    cell = f'<span style="color:#dc3545;font-weight:600" title="{err_msg}">&#10060; FAIL</span>'
                else:
                    cell = '<span style="color:#999">—</span>'
                fmt_cells += f"<td>{cell}</td>"

            rows += (
                f"<tr class='{status_class}'>"
                f"<td>{file_status_icon}</td>"
                f"<td>{html.escape(fr.workflow_name)}</td>"
                f"{fmt_cells}"
                f"<td>{best_fmt_html}</td>"
                f"<td>{fr.metrics.coverage_percentage:.0f}%</td>"
                f"<td>{fr.metrics.duration_seconds:.2f}s</td>"
                f"</tr>"
            )

        per_fmt_counts = result.per_format_success_counts()
        per_fmt_summary = "".join(
            f'<div class="metric"><div class="value">{per_fmt_counts.get(fmt, 0)}</div>'
            f'<div class="label">{html.escape(_FORMAT_LABELS[fmt])} OK</div></div>'
            for fmt in _FORMAT_KEYS
        )

        html_content = f"""<!DOCTYPE html>
<html>
<head>
<title>a2d Batch Conversion Report (multi-format)</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 2rem; }}
h1 {{ color: #1b3a57; }}
h2 {{ color: #2d6a9f; margin-top: 2rem; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #f2f2f2; }}
tr.success {{ background: #f0fff0; }}
tr.failure {{ background: #fff0f0; }}
.metrics {{ display: flex; gap: 1rem; margin: 1rem 0; flex-wrap: wrap; }}
.metric {{ background: #f8f9fb; border-radius: 8px; padding: 1rem 1.5rem; text-align: center; }}
.metric .value {{ font-size: 1.5rem; font-weight: bold; }}
.metric .label {{ font-size: 0.85rem; color: #666; }}
</style>
</head>
<body>
<h1>a2d Batch Conversion Report (multi-format)</h1>

<div class="metrics">
<div class="metric"><div class="value">{bm.total_files}</div><div class="label">Total Files</div></div>
<div class="metric"><div class="value">{bm.successful_files}</div><div class="label">All formats OK</div></div>
<div class="metric"><div class="value">{bm.partial_files}</div><div class="label">Partial</div></div>
<div class="metric"><div class="value">{bm.failed_files}</div><div class="label">Failed</div></div>
<div class="metric"><div class="value">{bm.duration_seconds:.2f}s</div><div class="label">Duration</div></div>
<div class="metric"><div class="value">{bm.avg_coverage_percentage:.0f}%</div><div class="label">Avg Coverage</div></div>
{per_fmt_summary}
</div>

<h2>Per-File Results</h2>
<table>
<thead><tr><th>Status</th><th>Workflow</th>{format_headers}<th>Best Format</th><th>Coverage</th><th>Duration</th></tr></thead>
<tbody>{rows if rows else '<tr><td colspan="9">No files processed</td></tr>'}</tbody>
</table>

</body>
</html>"""

        output_path.write_text(html_content)

    def _serialize_multi_file_result(self, fr: MultiFormatFileResult) -> dict:
        """Serialize a multi-format file result for JSON output."""
        data: dict = {
            "file_path": fr.file_path,
            "workflow_name": fr.workflow_name,
            "success": fr.success,
            "metrics": fr.metrics.to_dict(),
            "parse_error": fr.parse_error.to_dict() if fr.parse_error else None,
            "best_format": (fr.multi_result.best_format if fr.multi_result is not None else ""),
            "formats": {},
        }
        if fr.multi_result is not None:
            for fmt_key, fmt_res in fr.multi_result.formats.items():
                fmt_dict: dict = {
                    "status": fmt_res.status,
                    "duration_ms": fmt_res.duration_ms,
                    "warnings": list(fmt_res.warnings),
                    "error": fmt_res.error,
                }
                if fmt_res.confidence is not None:
                    fmt_dict["confidence"] = fmt_res.confidence.to_dict()
                if fmt_res.output is not None:
                    fmt_dict["files_generated"] = len(fmt_res.output.files)
                    fmt_dict["stats"] = dict(fmt_res.output.stats)
                data["formats"][fmt_key] = fmt_dict
        return data
