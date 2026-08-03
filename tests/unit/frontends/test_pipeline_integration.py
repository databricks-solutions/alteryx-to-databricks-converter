"""Integration: a dbt project flows through the whole IR pipeline."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from a2d.cli import app
from a2d.config import ConversionConfig, OutputFormat
from a2d.frontends.dbt import DbtFrontend
from a2d.pipeline import ConversionPipeline

runner = CliRunner()

DBT_DIR = Path(__file__).parent.parent.parent / "fixtures" / "dbt"


class TestDbtThroughPipeline:
    def test_dbt_manifest_builds_ir_and_generates(self):
        pipeline = ConversionPipeline(
            ConversionConfig(output_format=OutputFormat.PYSPARK),
            frontend=DbtFrontend(),
        )
        result = pipeline.convert(DBT_DIR)
        # 1 source + 1 seed + 2 models = 4 IR nodes; deps → 3 edges.
        assert result.dag.node_count == 4
        assert result.dag.edge_count == 3
        assert result.output.files  # generated something

    def test_alteryx_default_path_unchanged(self):
        # No frontend passed → Alteryx by default; existing behaviour preserved.
        wf = Path(__file__).parent.parent.parent / "fixtures" / "workflows" / "simple_filter.yxmd"
        pipeline = ConversionPipeline(ConversionConfig(output_format=OutputFormat.PYSPARK))
        result = pipeline.convert(wf)
        assert result.dag.node_count > 0


class TestConvertCliFrontend:
    # The dbt frontend is keyed on manifest.json; pass the file so the CLI takes
    # its single-file path (directory mode globs for *.yxmd).
    MANIFEST = DBT_DIR / "manifest.json"

    def test_convert_dbt_via_frontend_flag(self, tmp_path):
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            ["convert", str(self.MANIFEST), "-f", "sql", "--frontend", "dbt", "-o", str(out), "-q"],
        )
        assert result.exit_code == 0, result.output
        assert (out / "sql").exists()

    def test_convert_dbt_autodetected(self, tmp_path):
        # No --frontend: manifest.json is auto-detected as dbt.
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            ["convert", str(self.MANIFEST), "-f", "sql", "-o", str(out), "-q"],
        )
        assert result.exit_code == 0, result.output

    def test_convert_unknown_frontend_errors(self, tmp_path):
        result = runner.invoke(
            app,
            ["convert", str(self.MANIFEST), "--frontend", "cobol", "-o", str(tmp_path / "o"), "-q"],
        )
        assert result.exit_code == 1
        assert "unknown frontend" in result.output
