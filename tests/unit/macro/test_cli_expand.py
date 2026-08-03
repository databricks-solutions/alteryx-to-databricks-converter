"""Tests for `a2d convert --expand-macros` end-to-end."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from a2d.cli import app

runner = CliRunner()

MACRO_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "macro"


class TestConvertExpandMacros:
    def test_expansion_inlines_macro_logic(self, tmp_path):
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "convert",
                str(MACRO_FIXTURES / "parent_with_macro.yxmd"),
                "-f",
                "pyspark",
                "--expand-macros",
                "-o",
                str(out),
                "-q",
            ],
        )
        assert result.exit_code == 0, result.output
        py = next((out / "pyspark").glob("*.py"))
        code = py.read_text()
        # The macro's Formula (Uppercase) is inlined as real PySpark.
        assert "F.upper" in code
        # No unsupported-node stub left behind. (The boilerplate header mentions
        # "TODO" generically, so assert on the concrete stub marker instead.)
        assert "manual conversion required" not in code

    def test_without_flag_macro_is_unsupported(self, tmp_path):
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "convert",
                str(MACRO_FIXTURES / "parent_with_macro.yxmd"),
                "-f",
                "pyspark",
                "-o",
                str(out),
                "-q",
            ],
        )
        assert result.exit_code == 0, result.output
        py = next((out / "pyspark").glob("*.py"))
        assert "F.upper" not in py.read_text()
