"""Tests for a2d.observability.batch module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from a2d.config import ConversionConfig, OutputFormat
from a2d.generators.base import GeneratedFile, GeneratedOutput
from a2d.ir.graph import WorkflowDAG
from a2d.observability.batch import (
    BatchConversionResult,
    BatchOrchestrator,
    FileConversionResult,
    _classify_exception,
)
from a2d.observability.errors import ConversionError, ErrorKind, ErrorSeverity
from a2d.observability.metrics import FileMetrics
from a2d.pipeline import ConversionResult

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "workflows"


def _make_config() -> ConversionConfig:
    return ConversionConfig(
        input_path=FIXTURES_DIR,
        output_dir=Path("/tmp/a2d-test"),
        output_format=OutputFormat.PYSPARK,
    )


def _make_mock_result(node_count: int = 5, edge_count: int = 4) -> ConversionResult:
    """Create a mock ConversionResult."""
    dag = MagicMock(spec=WorkflowDAG)
    dag.node_count = node_count
    dag.edge_count = edge_count

    output = GeneratedOutput(
        files=[GeneratedFile("test.py", "# test", "python")],
        warnings=["test warning"],
        stats={"total_nodes": node_count, "supported_nodes": node_count - 1},
    )

    parsed = MagicMock()
    parsed.file_path = "/test.yxmd"

    return ConversionResult(
        output=output,
        dag=dag,
        parsed_workflow=parsed,
        warnings=["test warning"],
    )


class TestClassifyException:
    def test_parse_error(self):
        assert _classify_exception(Exception("XML parse error")) == ErrorKind.PARSING

    def test_conversion_error(self):
        assert _classify_exception(Exception("unsupported tool type")) == ErrorKind.CONVERSION

    def test_generation_error(self):
        assert _classify_exception(Exception("jinja template failed")) == ErrorKind.GENERATION

    def test_io_error(self):
        assert _classify_exception(FileNotFoundError("no such file")) == ErrorKind.IO
        assert _classify_exception(PermissionError("denied")) == ErrorKind.IO

    def test_internal_error(self):
        assert _classify_exception(RuntimeError("something broke")) == ErrorKind.INTERNAL


class TestFileConversionResult:
    def test_creation(self):
        fr = FileConversionResult(
            file_path="/test.yxmd",
            workflow_name="test",
            success=True,
        )
        assert fr.file_path == "/test.yxmd"
        assert fr.workflow_name == "test"
        assert fr.success is True
        assert fr.conversion_result is None
        assert fr.errors == []


class TestBatchConversionResult:
    def test_success_count(self):
        results = [
            FileConversionResult(file_path="a.yxmd", workflow_name="a", success=True),
            FileConversionResult(file_path="b.yxmd", workflow_name="b", success=True),
            FileConversionResult(file_path="c.yxmd", workflow_name="c", success=False),
        ]
        batch = BatchConversionResult(file_results=results)
        assert batch.success_count == 2
        assert batch.failure_count == 1

    def test_partial_count(self):
        results = [
            FileConversionResult(
                file_path="a.yxmd",
                workflow_name="a",
                success=True,
                errors=[
                    ConversionError(
                        kind=ErrorKind.CONVERSION,
                        severity=ErrorSeverity.WARNING,
                        message="warning",
                    )
                ],
            ),
        ]
        batch = BatchConversionResult(file_results=results)
        assert batch.partial_count == 1
        assert batch.success_count == 0

    def test_errors_by_kind(self):
        err1 = ConversionError(kind=ErrorKind.PARSING, severity=ErrorSeverity.ERROR, message="a")
        err2 = ConversionError(kind=ErrorKind.PARSING, severity=ErrorSeverity.ERROR, message="b")
        err3 = ConversionError(kind=ErrorKind.IO, severity=ErrorSeverity.ERROR, message="c")
        results = [
            FileConversionResult(file_path="a.yxmd", workflow_name="a", success=False, errors=[err1, err2]),
            FileConversionResult(file_path="b.yxmd", workflow_name="b", success=False, errors=[err3]),
        ]
        batch = BatchConversionResult(file_results=results)
        by_kind = batch.errors_by_kind()
        assert len(by_kind[ErrorKind.PARSING]) == 2
        assert len(by_kind[ErrorKind.IO]) == 1

    def test_errors_by_severity(self):
        err1 = ConversionError(kind=ErrorKind.PARSING, severity=ErrorSeverity.ERROR, message="a")
        err2 = ConversionError(kind=ErrorKind.CONVERSION, severity=ErrorSeverity.WARNING, message="b")
        results = [
            FileConversionResult(file_path="a.yxmd", workflow_name="a", success=False, errors=[err1, err2]),
        ]
        batch = BatchConversionResult(file_results=results)
        by_severity = batch.errors_by_severity()
        assert len(by_severity[ErrorSeverity.ERROR]) == 1
        assert len(by_severity[ErrorSeverity.WARNING]) == 1

    def test_empty_batch(self):
        batch = BatchConversionResult()
        assert batch.success_count == 0
        assert batch.failure_count == 0
        assert batch.partial_count == 0
        assert batch.errors_by_kind() == {}


class TestBatchOrchestrator:
    @patch.object(BatchOrchestrator, "_convert_single_with_tracking")
    def test_convert_batch_calls_single(self, mock_convert):
        """Verify convert_batch calls _convert_single_with_tracking for each file."""
        config = _make_config()
        orchestrator = BatchOrchestrator(config)

        mock_convert.return_value = FileConversionResult(
            file_path="test.yxmd",
            workflow_name="test",
            success=True,
            metrics=FileMetrics(success=True, coverage_percentage=100.0),
        )

        paths = [Path("a.yxmd"), Path("b.yxmd")]
        result = orchestrator.convert_batch(paths)

        assert mock_convert.call_count == 2
        assert len(result.file_results) == 2
        assert result.batch_metrics.total_files == 2

    @patch.object(BatchOrchestrator, "_convert_single_with_tracking")
    def test_progress_callback(self, mock_convert):
        """Verify progress callback is called correctly."""
        config = _make_config()
        orchestrator = BatchOrchestrator(config)

        mock_convert.return_value = FileConversionResult(
            file_path="test.yxmd",
            workflow_name="test",
            success=True,
            metrics=FileMetrics(success=True, coverage_percentage=100.0),
        )

        callback = MagicMock()
        paths = [Path("a.yxmd"), Path("b.yxmd"), Path("c.yxmd")]
        orchestrator.convert_batch(paths, progress_callback=callback)

        assert callback.call_count == 3
        callback.assert_any_call(1, 3, "a.yxmd")
        callback.assert_any_call(2, 3, "b.yxmd")
        callback.assert_any_call(3, 3, "c.yxmd")

    def test_single_with_tracking_success(self):
        """Test _convert_single_with_tracking with a successful conversion."""
        config = _make_config()
        orchestrator = BatchOrchestrator(config)
        mock_result = _make_mock_result()

        with patch.object(orchestrator.pipeline, "convert", return_value=mock_result):
            fr = orchestrator._convert_single_with_tracking(Path("/test.yxmd"))

        assert fr.success is True
        assert fr.workflow_name == "test"
        assert fr.metrics.node_count == 5
        assert fr.metrics.edge_count == 4
        assert fr.metrics.files_generated == 1
        assert fr.conversion_result is not None

    def test_single_with_tracking_failure(self):
        """Test _convert_single_with_tracking with a failing conversion."""
        config = _make_config()
        orchestrator = BatchOrchestrator(config)

        with patch.object(orchestrator.pipeline, "convert", side_effect=ValueError("broken")):
            fr = orchestrator._convert_single_with_tracking(Path("/bad.yxmd"))

        assert fr.success is False
        assert fr.workflow_name == "bad"
        assert len(fr.errors) == 1
        assert fr.errors[0].kind == ErrorKind.INTERNAL
        assert fr.errors[0].severity == ErrorSeverity.ERROR
        assert "broken" in fr.errors[0].message
        assert fr.conversion_result is None

    def test_single_with_tracking_collects_warnings(self):
        """Test that warnings from conversion result are captured as errors."""
        config = _make_config()
        orchestrator = BatchOrchestrator(config)
        mock_result = _make_mock_result()

        with patch.object(orchestrator.pipeline, "convert", return_value=mock_result):
            fr = orchestrator._convert_single_with_tracking(Path("/test.yxmd"))

        warning_errors = [e for e in fr.errors if e.severity == ErrorSeverity.WARNING]
        assert len(warning_errors) == 1
        assert warning_errors[0].message == "test warning"

    def test_batch_with_fixture_files(self):
        """Integration test using real fixture .yxmd files (if available)."""
        if not FIXTURES_DIR.exists():
            return

        fixture_files = sorted(FIXTURES_DIR.glob("*.yxmd"))
        if not fixture_files:
            return

        config = _make_config()
        orchestrator = BatchOrchestrator(config)
        result = orchestrator.convert_batch(fixture_files)

        assert result.batch_metrics.total_files == len(fixture_files)
        # Each file should produce either success or structured failure
        for fr in result.file_results:
            if not fr.success:
                assert len(fr.errors) > 0
                assert all(isinstance(e, ConversionError) for e in fr.errors)


class TestBatchOrchestratorMultiFormat:
    """Tests for the multi-format batch path (parses each file once,
    runs all 4 generators in a single pass)."""

    def test_convert_batch_multi_format_with_fixtures(self):
        """Real fixtures: every file should produce all 4 format outcomes."""
        if not FIXTURES_DIR.exists():
            return
        fixture_files = sorted(FIXTURES_DIR.glob("*.yxmd"))
        if not fixture_files:
            return

        config = _make_config()
        orchestrator = BatchOrchestrator(config)
        result = orchestrator.convert_batch_multi_format(fixture_files)

        assert result.batch_metrics.total_files == len(fixture_files)
        for fr in result.file_results:
            # Either parse_error (None) + multi_result, or parse_error + None
            if fr.parse_error is None:
                assert fr.multi_result is not None
                assert set(fr.multi_result.formats.keys()) == {"pyspark", "dlt", "sql", "lakeflow"}
            else:
                assert fr.multi_result is None

    def test_per_format_success_counts(self):
        """Per-format counts should never exceed total file count."""
        if not FIXTURES_DIR.exists():
            return
        fixture_files = sorted(FIXTURES_DIR.glob("*.yxmd"))
        if not fixture_files:
            return

        config = _make_config()
        orchestrator = BatchOrchestrator(config)
        result = orchestrator.convert_batch_multi_format(fixture_files)
        counts = result.per_format_success_counts()
        for fmt, count in counts.items():
            assert 0 <= count <= len(fixture_files), fmt

    def test_progress_callback_multi(self):
        """Progress callback fires once per file."""
        if not FIXTURES_DIR.exists():
            return
        fixture_files = sorted(FIXTURES_DIR.glob("*.yxmd"))[:1]  # one file is enough
        if not fixture_files:
            return

        config = _make_config()
        orchestrator = BatchOrchestrator(config)
        callback = MagicMock()
        orchestrator.convert_batch_multi_format(fixture_files, progress_callback=callback)
        assert callback.call_count == len(fixture_files)

    def test_format_status_helper(self):
        """``MultiFormatFileResult.format_status`` returns the right string."""
        from a2d.observability.batch import MultiFormatFileResult

        empty = MultiFormatFileResult(file_path="/x.yxmd", workflow_name="x", multi_result=None)
        assert empty.format_status("pyspark") == "missing"
        assert empty.success is False
