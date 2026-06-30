"""Tests for the base code generator, including syntax validation."""

from __future__ import annotations

from a2d.generators.base import CodeGenerator


class TestValidatePythonSyntax:
    def test_valid_python(self):
        result = CodeGenerator._validate_python_syntax("x = 1\ny = x + 2\n")
        assert result == []

    def test_invalid_python(self):
        result = CodeGenerator._validate_python_syntax("def foo(\n", "test.py")
        assert len(result) == 1
        assert "Syntax error" in result[0]
        assert "test.py" in result[0]

    def test_databricks_magic_stripped(self):
        code = "# Databricks notebook source\n# COMMAND ----------\n%sql SELECT 1\nx = 1\n"
        result = CodeGenerator._validate_python_syntax(code)
        assert result == []

    def test_magic_command_commented_out(self):
        code = "%md\n# Hello\nx = 1\n"
        result = CodeGenerator._validate_python_syntax(code)
        assert result == []

    def test_empty_code_is_valid(self):
        result = CodeGenerator._validate_python_syntax("")
        assert result == []

    def test_syntax_error_includes_line_number(self):
        code = "x = 1\nif True\n  pass\n"
        result = CodeGenerator._validate_python_syntax(code, "broken.py")
        assert len(result) == 1
        assert "line" in result[0].lower()
