"""Structured error tracking for the conversion pipeline."""

from __future__ import annotations

import traceback as tb_module
from dataclasses import dataclass
from enum import Enum


class ErrorKind(Enum):
    """Stage of the pipeline where the error occurred."""

    PARSING = "parsing"
    CONVERSION = "conversion"
    GENERATION = "generation"
    VALIDATION = "validation"
    IO = "io"
    INTERNAL = "internal"


class ErrorSeverity(Enum):
    """Severity level of the error."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class ConversionError:
    """A structured error from the conversion pipeline."""

    kind: ErrorKind
    severity: ErrorSeverity
    message: str
    file_path: str | None = None
    node_id: int | None = None
    tool_type: str | None = None
    code: str | None = None
    traceback: str | None = None

    @classmethod
    def from_exception(
        cls,
        exc: Exception,
        kind: ErrorKind,
        *,
        file_path: str | None = None,
        node_id: int | None = None,
        tool_type: str | None = None,
    ) -> ConversionError:
        """Create a ConversionError from a caught exception."""
        return cls(
            kind=kind,
            severity=ErrorSeverity.ERROR,
            message=str(exc),
            file_path=file_path,
            node_id=node_id,
            tool_type=tool_type,
            code=type(exc).__name__,
            traceback=tb_module.format_exc(),
        )

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON output."""
        return {
            "kind": self.kind.value,
            "severity": self.severity.value,
            "message": self.message,
            "file_path": self.file_path,
            "node_id": self.node_id,
            "tool_type": self.tool_type,
            "code": self.code,
            "traceback": self.traceback,
        }
