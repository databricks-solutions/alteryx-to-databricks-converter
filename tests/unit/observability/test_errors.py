"""Tests for a2d.observability.errors module."""

from __future__ import annotations

from a2d.observability.errors import ConversionError, ErrorKind, ErrorSeverity


class TestErrorKind:
    def test_enum_values(self):
        assert ErrorKind.PARSING.value == "parsing"
        assert ErrorKind.CONVERSION.value == "conversion"
        assert ErrorKind.GENERATION.value == "generation"
        assert ErrorKind.VALIDATION.value == "validation"
        assert ErrorKind.IO.value == "io"
        assert ErrorKind.INTERNAL.value == "internal"

    def test_all_kinds_exist(self):
        assert len(ErrorKind) == 6


class TestErrorSeverity:
    def test_enum_values(self):
        assert ErrorSeverity.INFO.value == "info"
        assert ErrorSeverity.WARNING.value == "warning"
        assert ErrorSeverity.ERROR.value == "error"

    def test_all_severities_exist(self):
        assert len(ErrorSeverity) == 3


class TestConversionError:
    def test_creation(self):
        err = ConversionError(
            kind=ErrorKind.PARSING,
            severity=ErrorSeverity.ERROR,
            message="Invalid XML",
            file_path="/some/file.yxmd",
            node_id=42,
            tool_type="AlteryxSelect",
        )
        assert err.kind == ErrorKind.PARSING
        assert err.severity == ErrorSeverity.ERROR
        assert err.message == "Invalid XML"
        assert err.file_path == "/some/file.yxmd"
        assert err.node_id == 42
        assert err.tool_type == "AlteryxSelect"
        assert err.code is None
        assert err.traceback is None

    def test_to_dict(self):
        err = ConversionError(
            kind=ErrorKind.CONVERSION,
            severity=ErrorSeverity.WARNING,
            message="Unsupported tool",
            file_path="/test.yxmd",
            node_id=5,
            tool_type="SpatialMatch",
            code="UnsupportedTool",
        )
        d = err.to_dict()
        assert d["kind"] == "conversion"
        assert d["severity"] == "warning"
        assert d["message"] == "Unsupported tool"
        assert d["file_path"] == "/test.yxmd"
        assert d["node_id"] == 5
        assert d["tool_type"] == "SpatialMatch"
        assert d["code"] == "UnsupportedTool"
        assert d["traceback"] is None

    def test_to_dict_includes_all_keys(self):
        err = ConversionError(
            kind=ErrorKind.IO,
            severity=ErrorSeverity.INFO,
            message="test",
        )
        d = err.to_dict()
        expected_keys = {"kind", "severity", "message", "file_path", "node_id", "tool_type", "code", "traceback"}
        assert set(d.keys()) == expected_keys

    def test_from_exception(self):
        try:
            raise ValueError("bad value")
        except ValueError as exc:
            err = ConversionError.from_exception(
                exc,
                ErrorKind.CONVERSION,
                file_path="/test.yxmd",
                node_id=10,
            )

        assert err.kind == ErrorKind.CONVERSION
        assert err.severity == ErrorSeverity.ERROR
        assert err.message == "bad value"
        assert err.file_path == "/test.yxmd"
        assert err.node_id == 10
        assert err.code == "ValueError"
        assert err.traceback is not None
        assert "ValueError" in err.traceback
