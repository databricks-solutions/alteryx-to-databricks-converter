"""Tests for the CLI entry point.

Covers all 5 commands (version, list-tools, convert, analyze, validate),
plus internal helpers (_parse_formats, _describe_file). All tests are hermetic:
they use ``tmp_path`` for output dirs and bundled fixtures for input.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from a2d.__about__ import __version__
from a2d.cli import _describe_file, _parse_formats, app
from a2d.config import OutputFormat

runner = CliRunner()

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "workflows"
SIMPLE_FIXTURE = FIXTURES_DIR / "simple_filter.yxmd"
COMPLEX_FIXTURE = FIXTURES_DIR / "complex_pipeline.yxmd"
JOIN_FIXTURE = FIXTURES_DIR / "join_and_summarize.yxmd"

ALL_FORMAT_DIRS = ("pyspark", "dlt", "sql", "lakeflow")


# ── Helpers ───────────────────────────────────────────────────────────


def _output_files(output_dir: Path, fmt: str) -> list[Path]:
    """Return all files under output_dir/<fmt>/ recursively."""
    sub = output_dir / fmt
    if not sub.exists():
        return []
    return [p for p in sub.rglob("*") if p.is_file()]


# ── A. Command discovery + help text ──────────────────────────────────


class TestHelpAndDiscovery:
    def test_top_level_help_exits_zero(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    def test_top_level_help_lists_all_five_commands(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for cmd in ("convert", "analyze", "validate", "list-tools", "version"):
            assert cmd in result.output, f"command {cmd!r} missing from help"

    def test_version_flag_long(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_version_flag_short(self):
        result = runner.invoke(app, ["-V"])
        assert result.exit_code == 0
        assert __version__ in result.output

    @pytest.mark.parametrize("cmd", ["convert", "analyze", "validate", "list-tools", "version"])
    def test_each_command_has_help(self, cmd):
        result = runner.invoke(app, [cmd, "--help"])
        assert result.exit_code == 0
        # help should at least mention the command name or some flag
        assert result.output.strip()

    def test_top_level_help_mentions_multi_format_default(self):
        # Lenient: assert the keyword "convert" + a hint at multi-format.
        # Copy may evolve, but the quick-start examples mention "ALL 4 formats".
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        # Be lenient: just look for "format" or "4" in the output.
        out_lower = result.output.lower()
        assert "format" in out_lower

    def test_convert_help_mentions_spark_declarative_pipelines(self):
        result = runner.invoke(app, ["convert", "--help"])
        assert result.exit_code == 0
        # The CLI documents dlt = "Spark Declarative Pipelines" in the --format help.
        assert "Spark Declarative Pipelines" in result.output


# ── B. version command ────────────────────────────────────────────────


class TestVersionCommand:
    def test_version_output(self):
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert __version__ in result.output


# ── C. list-tools command ─────────────────────────────────────────────


class TestListToolsCommand:
    def test_list_tools_runs(self):
        result = runner.invoke(app, ["list-tools"])
        assert result.exit_code == 0
        assert "Tool Type" in result.output

    def test_list_tools_supported_only(self):
        result = runner.invoke(app, ["list-tools", "--supported"])
        assert result.exit_code == 0
        assert "Supported" in result.output

    def test_list_tools_output_nonempty(self):
        result = runner.invoke(app, ["list-tools"])
        assert result.exit_code == 0
        # Reasonable lower bound: at least a header row + some data rows.
        non_empty_lines = [ln for ln in result.output.splitlines() if ln.strip()]
        assert len(non_empty_lines) > 5

    def test_list_tools_contains_known_types(self):
        result = runner.invoke(app, ["list-tools"])
        assert result.exit_code == 0
        # A handful of fundamental tools we expect to always be present.
        for tool in ("Filter", "Select", "Join"):
            assert tool in result.output, f"expected tool {tool!r} not listed"

    def test_list_tools_supported_short_flag(self):
        result = runner.invoke(app, ["list-tools", "-s"])
        assert result.exit_code == 0
        assert "Supported" in result.output


# ── D. convert command — happy path ───────────────────────────────────


class TestConvertCommandHappyPath:
    def test_convert_single_file_emits_all_four_format_subdirs(self, tmp_path):
        out = tmp_path / "out"
        result = runner.invoke(app, ["convert", str(SIMPLE_FIXTURE), "--output-dir", str(out)])
        assert result.exit_code == 0, result.output
        for fmt in ALL_FORMAT_DIRS:
            assert (out / fmt).is_dir(), f"missing per-format subdir {fmt}/"

    def test_convert_each_subdir_has_at_least_one_artifact(self, tmp_path):
        out = tmp_path / "out"
        result = runner.invoke(app, ["convert", str(SIMPLE_FIXTURE), "--output-dir", str(out)])
        assert result.exit_code == 0, result.output
        for fmt in ALL_FORMAT_DIRS:
            files = _output_files(out, fmt)
            # Each format produces .py and/or .sql artefacts; allow either.
            has_code = any(p.suffix in (".py", ".sql") for p in files)
            assert has_code, f"format {fmt} produced no .py/.sql files: {files}"

    def test_convert_format_filter_pyspark_only(self, tmp_path):
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "convert",
                str(SIMPLE_FIXTURE),
                "--output-dir",
                str(out),
                "--format",
                "pyspark",
            ],
        )
        assert result.exit_code == 0, result.output
        assert (out / "pyspark").is_dir()
        for fmt in ("dlt", "sql", "lakeflow"):
            assert not (out / fmt).is_dir(), f"unexpected subdir {fmt}/ created"

    def test_convert_format_filter_pyspark_and_sql(self, tmp_path):
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "convert",
                str(SIMPLE_FIXTURE),
                "--output-dir",
                str(out),
                "--format",
                "pyspark,sql",
            ],
        )
        assert result.exit_code == 0, result.output
        assert (out / "pyspark").is_dir()
        assert (out / "sql").is_dir()
        for fmt in ("dlt", "lakeflow"):
            assert not (out / fmt).is_dir(), f"unexpected subdir {fmt}/ created"

    def test_convert_format_all_emits_all_four(self, tmp_path):
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "convert",
                str(SIMPLE_FIXTURE),
                "--output-dir",
                str(out),
                "--format",
                "all",
            ],
        )
        assert result.exit_code == 0, result.output
        for fmt in ALL_FORMAT_DIRS:
            assert (out / fmt).is_dir(), f"missing subdir {fmt}/"

    def test_convert_format_short_flag(self, tmp_path):
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "convert",
                str(SIMPLE_FIXTURE),
                "-o",
                str(out),
                "-f",
                "pyspark",
            ],
        )
        assert result.exit_code == 0, result.output
        assert (out / "pyspark").is_dir()

    def test_convert_bad_format_string_exits_nonzero(self, tmp_path):
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "convert",
                str(SIMPLE_FIXTURE),
                "--output-dir",
                str(out),
                "--format",
                "bogus",
            ],
        )
        assert result.exit_code != 0
        # Lenient: error message should mention "Invalid" or list valid formats.
        out_lower = result.output.lower()
        assert "invalid" in out_lower or "valid" in out_lower

    def test_convert_no_comments_succeeds(self, tmp_path):
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "convert",
                str(SIMPLE_FIXTURE),
                "--output-dir",
                str(out),
                "--no-comments",
                "--format",
                "pyspark",
            ],
        )
        assert result.exit_code == 0, result.output
        files = _output_files(out, "pyspark")
        assert any(p.suffix == ".py" for p in files)

    def test_convert_with_catalog_and_schema_succeeds(self, tmp_path):
        # Note: the simple_filter fixture uses TextInput (literal data) and CSV
        # outputs, so it doesn't reference a UC table. We assert the flags are
        # accepted and conversion succeeds; deep propagation testing belongs
        # in generator-level tests where the UC reference path is exercised.
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "convert",
                str(SIMPLE_FIXTURE),
                "--output-dir",
                str(out),
                "--catalog",
                "mycat",
                "--schema",
                "myschema",
                "--format",
                "sql",
            ],
        )
        assert result.exit_code == 0, result.output
        files = _output_files(out, "sql")
        assert any(p.suffix == ".sql" for p in files), "no .sql files produced"

    def test_convert_complex_fixture_succeeds(self, tmp_path):
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "convert",
                str(COMPLEX_FIXTURE),
                "--output-dir",
                str(out),
                "--format",
                "pyspark",
            ],
        )
        assert result.exit_code == 0, result.output
        files = _output_files(out, "pyspark")
        assert any(p.suffix == ".py" for p in files)

    def test_convert_quiet_flag_runs(self, tmp_path):
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "convert",
                str(SIMPLE_FIXTURE),
                "--output-dir",
                str(out),
                "--format",
                "pyspark",
                "--quiet",
            ],
        )
        assert result.exit_code == 0, result.output


# ── D2. convert command — --cloud flag ────────────────────────────────


class TestConvertCloudFlag:
    """Cloud-aware node_type_id plumbing — flag must reach the workflow.json."""

    def _read_workflow_json_body(self, sub: Path) -> dict:
        """Locate and parse the generated workflow.json under the format subdir.

        Strips the leading // header comments since standard json doesn't
        support comments (we re-add them for human readability).
        """
        candidates = list(sub.rglob("*_workflow.json"))
        assert candidates, f"no *_workflow.json under {sub}"
        content = candidates[0].read_text()
        body = "".join(ln for ln in content.splitlines(keepends=True) if not ln.lstrip().startswith("//"))
        return json.loads(body)

    def test_convert_cloud_azure_emits_standard_ds3_v2(self, tmp_path):
        """--cloud azure must produce node_type_id = Standard_DS3_v2."""
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "convert",
                str(SIMPLE_FIXTURE),
                "--output-dir",
                str(out),
                "--format",
                "pyspark",
                "--cloud",
                "azure",
            ],
        )
        assert result.exit_code == 0, result.output
        job = self._read_workflow_json_body(out / "pyspark")
        cluster = job["job_clusters"][0]
        assert cluster["new_cluster"]["node_type_id"] == "Standard_DS3_v2"
        # Task should reference the job_cluster_key, not embed an inline cluster.
        assert job["tasks"][0]["job_cluster_key"] == "main"

    def test_convert_cloud_aws_default_is_i3_xlarge(self, tmp_path):
        """Backward compat: omitting --cloud should produce i3.xlarge."""
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "convert",
                str(SIMPLE_FIXTURE),
                "--output-dir",
                str(out),
                "--format",
                "pyspark",
            ],
        )
        assert result.exit_code == 0, result.output
        job = self._read_workflow_json_body(out / "pyspark")
        cluster = job["job_clusters"][0]
        assert cluster["new_cluster"]["node_type_id"] == "i3.xlarge"

    def test_convert_cloud_gcp_emits_n1_highmem(self, tmp_path):
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "convert",
                str(SIMPLE_FIXTURE),
                "--output-dir",
                str(out),
                "--format",
                "pyspark",
                "--cloud",
                "gcp",
            ],
        )
        assert result.exit_code == 0, result.output
        job = self._read_workflow_json_body(out / "pyspark")
        assert job["job_clusters"][0]["new_cluster"]["node_type_id"] == "n1-highmem-4"

    def test_convert_cloud_invalid_exits_nonzero(self, tmp_path):
        """An unrecognized cloud should fail fast with a helpful message."""
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "convert",
                str(SIMPLE_FIXTURE),
                "--output-dir",
                str(out),
                "--cloud",
                "ibm-cloud",
            ],
        )
        assert result.exit_code != 0
        assert "cloud" in result.output.lower()

    def test_convert_help_documents_cloud_flag(self):
        """--help should document --cloud and its default."""
        result = runner.invoke(app, ["convert", "--help"])
        assert result.exit_code == 0
        # Strip ANSI color codes — Typer/Rich injects them in help output
        # and inserts them inside `--cloud` (rendering as `-\x1b[…]m-cloud`).
        # Locally a TTY-aware test runner may strip them, but in CI they
        # remain literal in `result.output` and break a substring search.
        import re

        plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "--cloud" in plain
        # Lenient: just make sure aws/azure/gcp are mentioned.
        plain_lower = plain.lower()
        assert "aws" in plain_lower
        assert "azure" in plain_lower


# ── E. convert command — edge cases ───────────────────────────────────


class TestConvertCommandEdgeCases:
    def test_convert_missing_file(self):
        result = runner.invoke(app, ["convert", "/nonexistent/path.yxmd"])
        assert result.exit_code != 0

    def test_convert_missing_file_helpful_error(self, tmp_path):
        missing = tmp_path / "doesnotexist.yxmd"
        result = runner.invoke(app, ["convert", str(missing)])
        assert result.exit_code != 0
        # Error mentions "not found" per cli.py.
        assert "not found" in result.output.lower()

    def test_convert_empty_file_does_not_crash(self, tmp_path):
        empty = tmp_path / "empty.yxmd"
        empty.write_text("")
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "convert",
                str(empty),
                "--output-dir",
                str(out),
                "--format",
                "pyspark",
            ],
        )
        # Per-format failure is non-fatal — but if ALL formats fail, exit != 0.
        # Either way the CLI must NOT raise an unhandled exception.
        assert result.exception is None or isinstance(result.exception, SystemExit), (
            f"unhandled exception: {result.exception!r}"
        )

    def test_convert_directory_without_batch_runs(self, tmp_path):
        # Copy a single fixture into a fresh dir to control scope.
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        shutil.copy(SIMPLE_FIXTURE, wf_dir / "simple_filter.yxmd")
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "convert",
                str(wf_dir),
                "--output-dir",
                str(out),
                "--format",
                "pyspark",
            ],
        )
        # Per cli.py: directory mode WITHOUT --batch goes through the
        # convert_batch branch; a single file should succeed.
        assert result.exit_code == 0, result.output
        assert (out / "pyspark").is_dir()

    def test_convert_directory_with_no_yxmd_files_exits_nonzero(self, tmp_path):
        empty_dir = tmp_path / "empty_dir"
        empty_dir.mkdir()
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "convert",
                str(empty_dir),
                "--output-dir",
                str(out),
                "--format",
                "pyspark",
            ],
        )
        assert result.exit_code != 0
        assert "no .yxmd" in result.output.lower() or "not found" in result.output.lower()

    def test_convert_batch_mode_on_directory(self, tmp_path):
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        shutil.copy(SIMPLE_FIXTURE, wf_dir / "simple_filter.yxmd")
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "convert",
                str(wf_dir),
                "--output-dir",
                str(out),
                "--batch",
                "--format",
                "pyspark",
                "--report-format",
                "json",
            ],
        )
        assert result.exit_code == 0, result.output
        # Batch mode writes a report file under the per-format subdir.
        report = out / "pyspark" / "batch_report.json"
        assert report.is_file(), f"batch report missing: {list((out / 'pyspark').iterdir())}"


# ── F. analyze command ────────────────────────────────────────────────


class TestAnalyzeCommand:
    def test_analyze_single_fixture_writes_html(self, tmp_path):
        out = tmp_path / "report"
        result = runner.invoke(
            app,
            ["analyze", str(SIMPLE_FIXTURE), "--output-dir", str(out)],
        )
        assert result.exit_code == 0, result.output
        assert (out / "migration_report.html").is_file()

    def test_analyze_directory_writes_report(self, tmp_path):
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        shutil.copy(SIMPLE_FIXTURE, wf_dir / "simple_filter.yxmd")
        shutil.copy(JOIN_FIXTURE, wf_dir / "join_and_summarize.yxmd")
        out = tmp_path / "report"
        result = runner.invoke(
            app,
            ["analyze", str(wf_dir), "--output-dir", str(out)],
        )
        assert result.exit_code == 0, result.output
        assert (out / "migration_report.html").is_file()

    def test_analyze_format_json(self, tmp_path):
        out = tmp_path / "report"
        result = runner.invoke(
            app,
            [
                "analyze",
                str(SIMPLE_FIXTURE),
                "--output-dir",
                str(out),
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0, result.output
        report = out / "migration_report.json"
        assert report.is_file()
        # Validate JSON parses.
        data = json.loads(report.read_text())
        assert isinstance(data, dict | list)

    def test_analyze_complexity_flag(self, tmp_path):
        out = tmp_path / "report"
        result = runner.invoke(
            app,
            [
                "analyze",
                str(SIMPLE_FIXTURE),
                "--output-dir",
                str(out),
                "--complexity",
            ],
        )
        assert result.exit_code == 0, result.output
        # Complexity table is printed to stdout.
        assert "Complexity" in result.output or "complexity" in result.output.lower()

    def test_analyze_missing_path_exits_nonzero(self, tmp_path):
        out = tmp_path / "report"
        result = runner.invoke(
            app,
            ["analyze", "/nonexistent/foo.yxmd", "--output-dir", str(out)],
        )
        assert result.exit_code != 0


# ── G. validate command ───────────────────────────────────────────────


class TestValidateCommand:
    def test_validate_succeeds_on_generated_pyspark(self, tmp_path):
        # First convert to produce a valid .py file.
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "convert",
                str(SIMPLE_FIXTURE),
                "--output-dir",
                str(out),
                "--format",
                "pyspark",
            ],
        )
        assert result.exit_code == 0, result.output
        py_files = [p for p in (out / "pyspark").rglob("*.py")]
        assert py_files, "no .py file produced"
        target = py_files[0]
        result2 = runner.invoke(app, ["validate", str(target)])
        assert result2.exit_code == 0, result2.output
        assert "Valid" in result2.output

    def test_validate_fails_on_broken_python(self, tmp_path):
        broken = tmp_path / "broken.py"
        broken.write_text("def broken(:\n    pass\n")  # Syntax error
        result = runner.invoke(app, ["validate", str(broken)])
        assert result.exit_code != 0
        assert "Invalid" in result.output

    def test_validate_missing_file(self, tmp_path):
        missing = tmp_path / "nope.py"
        result = runner.invoke(app, ["validate", str(missing)])
        # Should not crash; exit non-zero or report invalid.
        assert result.exit_code != 0 or "Invalid" in result.output


# ── H. Internal helpers ───────────────────────────────────────────────


class TestParseFormats:
    def test_parse_formats_all(self):
        result = _parse_formats("all")
        assert result == list(OutputFormat)
        assert len(result) == 4

    def test_parse_formats_single(self):
        result = _parse_formats("pyspark")
        assert result == [OutputFormat.PYSPARK]

    def test_parse_formats_multi(self):
        result = _parse_formats("pyspark,sql")
        assert result == [OutputFormat.PYSPARK, OutputFormat.SQL]

    def test_parse_formats_whitespace_tolerated(self):
        result = _parse_formats("pyspark, dlt , lakeflow")
        assert result == [OutputFormat.PYSPARK, OutputFormat.DLT, OutputFormat.LAKEFLOW]

    def test_parse_formats_dedupes(self):
        result = _parse_formats("pyspark,pyspark,sql")
        assert result == [OutputFormat.PYSPARK, OutputFormat.SQL]

    def test_parse_formats_case_insensitive(self):
        result = _parse_formats("PySpark,SQL")
        assert result == [OutputFormat.PYSPARK, OutputFormat.SQL]

    def test_parse_formats_invalid_raises(self):
        with pytest.raises(ValueError) as exc_info:
            _parse_formats("bogus")
        msg = str(exc_info.value).lower()
        assert "invalid" in msg
        # Helpful message lists valid formats.
        assert "pyspark" in msg

    def test_parse_formats_empty_raises(self):
        with pytest.raises(ValueError):
            _parse_formats("")

    def test_parse_formats_whitespace_only_raises(self):
        with pytest.raises(ValueError):
            _parse_formats("   ")


class TestDescribeFile:
    def test_describe_py(self):
        assert _describe_file("foo.py") == "PySpark notebook"

    def test_describe_sql(self):
        assert _describe_file("foo.sql") == "SQL script"

    def test_describe_workflow_json(self):
        assert _describe_file("my_workflow.json") == "Databricks workflow definition"

    def test_describe_expression_audit(self):
        assert _describe_file("foo_expression_audit.csv") == "Expression transformation audit"

    def test_describe_unknown_returns_empty(self):
        assert _describe_file("foo.xyz") == ""
