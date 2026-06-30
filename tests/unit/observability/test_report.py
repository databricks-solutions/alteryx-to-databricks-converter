"""Tests for a2d.observability.report module."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from a2d.observability.batch import BatchConversionResult, FileConversionResult
from a2d.observability.errors import ConversionError, ErrorKind, ErrorSeverity
from a2d.observability.metrics import BatchMetrics, FileMetrics
from a2d.observability.report import OutcomeReportGenerator


def _make_batch_result() -> BatchConversionResult:
    """Create a sample BatchConversionResult for testing."""
    now = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    fr1 = FileConversionResult(
        file_path="/a.yxmd",
        workflow_name="a",
        success=True,
        errors=[
            ConversionError(
                kind=ErrorKind.CONVERSION,
                severity=ErrorSeverity.WARNING,
                message="Unsupported tool ignored",
                file_path="/a.yxmd",
            )
        ],
        metrics=FileMetrics(
            file_path="/a.yxmd",
            workflow_name="a",
            started_at=now,
            completed_at=now,
            duration_seconds=1.2,
            node_count=10,
            edge_count=9,
            supported_node_count=9,
            unsupported_node_count=1,
            coverage_percentage=90.0,
            files_generated=2,
            success=True,
        ),
    )
    fr2 = FileConversionResult(
        file_path="/b.yxmd",
        workflow_name="b",
        success=False,
        errors=[
            ConversionError(
                kind=ErrorKind.PARSING,
                severity=ErrorSeverity.ERROR,
                message="Invalid XML",
                file_path="/b.yxmd",
                code="XMLSyntaxError",
            )
        ],
        metrics=FileMetrics(
            file_path="/b.yxmd",
            workflow_name="b",
            started_at=now,
            completed_at=now,
            duration_seconds=0.1,
            success=False,
        ),
    )

    batch_metrics = BatchMetrics(
        started_at=now,
        completed_at=now,
        duration_seconds=1.3,
        total_files=2,
        successful_files=1,
        failed_files=1,
        partial_files=0,
        total_nodes=10,
        total_errors=1,
        total_warnings=1,
        avg_coverage_percentage=90.0,
    )

    return BatchConversionResult(
        file_results=[fr1, fr2],
        batch_metrics=batch_metrics,
    )


class TestOutcomeReportJSON:
    def test_generate_json(self, tmp_path: Path):
        result = _make_batch_result()
        report_gen = OutcomeReportGenerator()
        output = tmp_path / "report.json"

        report_gen.generate_json(result, output)

        assert output.exists()
        data = json.loads(output.read_text())

        assert "batch_metrics" in data
        assert "file_results" in data
        assert "error_summary" in data

        assert data["batch_metrics"]["total_files"] == 2
        assert data["batch_metrics"]["successful_files"] == 1
        assert data["batch_metrics"]["failed_files"] == 1

        assert len(data["file_results"]) == 2
        assert data["file_results"][0]["success"] is True
        assert data["file_results"][1]["success"] is False

    def test_json_error_summary(self, tmp_path: Path):
        result = _make_batch_result()
        report_gen = OutcomeReportGenerator()
        output = tmp_path / "report.json"

        report_gen.generate_json(result, output)
        data = json.loads(output.read_text())

        summary = data["error_summary"]
        assert summary["total"] == 2
        assert summary["by_kind"]["parsing"] == 1
        assert summary["by_kind"]["conversion"] == 1
        assert summary["by_severity"]["error"] == 1
        assert summary["by_severity"]["warning"] == 1


class TestOutcomeReportJSONL:
    def test_generate_jsonl(self, tmp_path: Path):
        result = _make_batch_result()
        report_gen = OutcomeReportGenerator()
        output = tmp_path / "report.jsonl"

        report_gen.generate_jsonl(result, output)

        assert output.exists()
        lines = [line for line in output.read_text().strip().split("\n") if line]

        # batch_start + 2 file_results + 2 error records = 5
        assert len(lines) == 5

        first = json.loads(lines[0])
        assert first["type"] == "batch_start"

        file_lines = [json.loads(ln) for ln in lines if json.loads(ln)["type"] == "file_result"]
        assert len(file_lines) == 2

        error_lines = [json.loads(ln) for ln in lines if json.loads(ln)["type"] == "error"]
        assert len(error_lines) == 2

    def test_jsonl_each_line_valid_json(self, tmp_path: Path):
        result = _make_batch_result()
        report_gen = OutcomeReportGenerator()
        output = tmp_path / "report.jsonl"

        report_gen.generate_jsonl(result, output)

        for line in output.read_text().strip().split("\n"):
            if line:
                parsed = json.loads(line)
                assert "type" in parsed
                assert "data" in parsed


class TestOutcomeReportHTML:
    def test_generate_html(self, tmp_path: Path):
        result = _make_batch_result()
        report_gen = OutcomeReportGenerator()
        output = tmp_path / "report.html"

        report_gen.generate_html(result, output)

        assert output.exists()
        html_content = output.read_text()

        assert "a2d Batch Conversion Report" in html_content
        assert "Total Files" in html_content
        assert "Successful" in html_content
        assert "Failed" in html_content

    def test_html_contains_workflow_names(self, tmp_path: Path):
        result = _make_batch_result()
        report_gen = OutcomeReportGenerator()
        output = tmp_path / "report.html"

        report_gen.generate_html(result, output)
        html_content = output.read_text()

        assert "workflow a" in html_content.lower() or ">a<" in html_content
        assert "workflow b" in html_content.lower() or ">b<" in html_content

    def test_html_error_breakdown(self, tmp_path: Path):
        result = _make_batch_result()
        report_gen = OutcomeReportGenerator()
        output = tmp_path / "report.html"

        report_gen.generate_html(result, output)
        html_content = output.read_text()

        assert "Error Breakdown" in html_content
        assert "parsing" in html_content


class TestOutcomeReportEmpty:
    def test_empty_batch_json(self, tmp_path: Path):
        result = BatchConversionResult()
        report_gen = OutcomeReportGenerator()
        output = tmp_path / "empty.json"

        report_gen.generate_json(result, output)
        data = json.loads(output.read_text())
        assert data["file_results"] == []
        assert data["error_summary"]["total"] == 0


def _make_multi_format_batch_result():
    """Build a synthetic MultiFormatBatchResult for report tests."""
    from unittest.mock import MagicMock

    from a2d.generators.base import GeneratedFile, GeneratedOutput
    from a2d.ir.graph import WorkflowDAG
    from a2d.observability.batch import MultiFormatBatchResult, MultiFormatFileResult
    from a2d.observability.metrics import BatchMetrics, FileMetrics
    from a2d.pipeline import FormatConversionResult, MultiFormatConversionResult

    now = datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc)

    def _make_format_result(fmt: str, status: str, duration_ms: float = 12.5):
        if status == "success":
            output = GeneratedOutput(
                files=[GeneratedFile(f"{fmt}.py", "# code", "python")],
                warnings=[],
                stats={"total_nodes": 5, "supported_nodes": 5},
            )
            return FormatConversionResult(
                format=fmt,
                status="success",
                output=output,
                warnings=[],
                confidence=None,
                duration_ms=duration_ms,
            )
        return FormatConversionResult(
            format=fmt,
            status="failed",
            output=None,
            warnings=[],
            confidence=None,
            error=f"{fmt} synthetic failure",
            duration_ms=duration_ms,
        )

    dag = MagicMock(spec=WorkflowDAG)
    dag.node_count = 5
    dag.edge_count = 4

    multi_a = MultiFormatConversionResult(
        parsed_workflow=MagicMock(),
        dag=dag,
        warnings=[],
        formats={
            "pyspark": _make_format_result("pyspark", "success"),
            "dlt": _make_format_result("dlt", "success"),
            "sql": _make_format_result("sql", "success"),
            "lakeflow": _make_format_result("lakeflow", "success"),
        },
        best_format="pyspark",
    )
    fr_a = MultiFormatFileResult(
        file_path="/a.yxmd",
        workflow_name="a",
        multi_result=multi_a,
        metrics=FileMetrics(
            file_path="/a.yxmd",
            workflow_name="a",
            started_at=now,
            completed_at=now,
            duration_seconds=1.0,
            node_count=5,
            edge_count=4,
            supported_node_count=5,
            unsupported_node_count=0,
            coverage_percentage=100.0,
            files_generated=4,
            success=True,
        ),
    )

    multi_b = MultiFormatConversionResult(
        parsed_workflow=MagicMock(),
        dag=dag,
        warnings=[],
        formats={
            "pyspark": _make_format_result("pyspark", "success"),
            "dlt": _make_format_result("dlt", "failed"),
            "sql": _make_format_result("sql", "success"),
            "lakeflow": _make_format_result("lakeflow", "failed"),
        },
        best_format="pyspark",
    )
    fr_b = MultiFormatFileResult(
        file_path="/b.yxmd",
        workflow_name="b",
        multi_result=multi_b,
        metrics=FileMetrics(
            file_path="/b.yxmd",
            workflow_name="b",
            started_at=now,
            completed_at=now,
            duration_seconds=2.5,
            node_count=5,
            edge_count=4,
            supported_node_count=4,
            unsupported_node_count=1,
            coverage_percentage=80.0,
            files_generated=2,
            success=True,
        ),
    )

    return MultiFormatBatchResult(
        file_results=[fr_a, fr_b],
        batch_metrics=BatchMetrics(
            started_at=now,
            completed_at=now,
            duration_seconds=3.5,
            total_files=2,
            successful_files=1,
            failed_files=0,
            partial_files=1,
            total_nodes=10,
            total_errors=2,
            total_warnings=0,
            avg_coverage_percentage=90.0,
        ),
    )


class TestMultiFormatReports:
    def test_generate_json_multi(self, tmp_path: Path):
        result = _make_multi_format_batch_result()
        report_gen = OutcomeReportGenerator()
        output = tmp_path / "multi.json"
        report_gen.generate_json_multi(result, output)
        data = json.loads(output.read_text())
        assert "batch_metrics" in data
        assert "per_format_success_counts" in data
        # File "a" has all 4 formats OK; "b" has 2/4. Aggregate = pyspark+sql 2/2.
        assert data["per_format_success_counts"]["pyspark"] == 2
        assert data["per_format_success_counts"]["dlt"] == 1
        assert data["per_format_success_counts"]["sql"] == 2
        assert data["per_format_success_counts"]["lakeflow"] == 1
        assert len(data["file_results"]) == 2
        # Each file has a per-format dict with status + duration_ms.
        for f in data["file_results"]:
            assert set(f["formats"].keys()) == {"pyspark", "dlt", "sql", "lakeflow"}
            for fmt_dict in f["formats"].values():
                assert fmt_dict["status"] in {"success", "failed"}
                assert "duration_ms" in fmt_dict

    def test_generate_jsonl_multi(self, tmp_path: Path):
        result = _make_multi_format_batch_result()
        report_gen = OutcomeReportGenerator()
        output = tmp_path / "multi.jsonl"
        report_gen.generate_jsonl_multi(result, output)
        lines = [json.loads(line) for line in output.read_text().strip().split("\n") if line]
        assert lines[0]["type"] == "batch_start"
        types = [ln["type"] for ln in lines]
        assert types.count("file_result") == 2
        # Two formats failed in file "b" (dlt + lakeflow).
        assert types.count("format_error") == 2
        # The format_status block should expose all 4 keys.
        for ln in lines:
            if ln["type"] == "file_result":
                assert set(ln["data"]["format_status"].keys()) == {"pyspark", "dlt", "sql", "lakeflow"}

    def test_generate_html_multi(self, tmp_path: Path):
        result = _make_multi_format_batch_result()
        report_gen = OutcomeReportGenerator()
        output = tmp_path / "multi.html"
        report_gen.generate_html_multi(result, output)
        text = output.read_text()
        assert "multi-format" in text.lower()
        # Per-format columns present
        assert "PySpark" in text
        assert "Spark Declarative Pipelines" in text
        assert "Spark SQL" in text
        assert "Lakeflow Designer" in text
        # File rows present
        assert ">a<" in text
        assert ">b<" in text
