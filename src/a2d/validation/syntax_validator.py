"""Python syntax validation for generated code."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ValidationResult:
    """Result of validating generated code."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    file_path: str = ""


class SyntaxValidator:
    """Validate Python code syntax using ast.parse()."""

    def validate_file(self, path: Path) -> ValidationResult:
        """Validate a Python file's syntax."""
        if not path.exists():
            return ValidationResult(
                is_valid=False,
                errors=[f"File not found: {path}"],
                file_path=str(path),
            )

        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return ValidationResult(
                is_valid=False,
                errors=[f"Could not read file: {e}"],
                file_path=str(path),
            )

        return self.validate_string(source, filename=str(path))

    def validate_string(self, code: str, filename: str = "<string>") -> ValidationResult:
        """Validate Python code string syntax."""
        # Strip Databricks notebook magic lines that would fail ast.parse
        cleaned = self._strip_notebook_magics(code)

        try:
            ast.parse(cleaned, filename=filename)
            return ValidationResult(
                is_valid=True,
                errors=[],
                file_path=filename,
            )
        except SyntaxError as e:
            error_msg = f"Syntax error at line {e.lineno}: {e.msg}"
            if e.text:
                error_msg += f" -> {e.text.strip()}"
            return ValidationResult(
                is_valid=False,
                errors=[error_msg],
                file_path=filename,
            )

    @staticmethod
    def _strip_notebook_magics(code: str) -> str:
        """Strip Databricks notebook magic commands and separators.

        Lines like ``# Databricks notebook source``, ``# COMMAND ----------``,
        ``# MAGIC %sql``, etc. are valid Python comments, but lines starting
        with ``%`` (magic commands) are not valid Python and need removal.
        """
        lines = code.split("\n")
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            # Remove IPython/Databricks magic lines (e.g., %sql, %pip)
            if stripped.startswith("%") and not stripped.startswith("%%"):
                cleaned_lines.append(f"# {stripped}")
            else:
                cleaned_lines.append(line)
        return "\n".join(cleaned_lines)
