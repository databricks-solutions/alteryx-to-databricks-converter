"""Integration tests using MIT-licensed Packt Publishing Alteryx workflows.

These 40 .yxmd files come from three Packt books (all MIT licensed):
  - Alteryx Designer Cookbook (2022)
  - Data Engineering with Alteryx (2022)
  - Advanced Alteryx (2020)

See tests/fixtures/packt/LICENSE for full attribution.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from a2d.config import ConversionConfig, OutputFormat
from a2d.parser.workflow_parser import WorkflowParser
from a2d.pipeline import ConversionPipeline, ConversionResult
from a2d.validation.syntax_validator import SyntaxValidator

PACKT_DIR = Path(__file__).parent.parent / "fixtures" / "packt"
PACKT_FILES = sorted(PACKT_DIR.glob("*.yxmd")) if PACKT_DIR.exists() else []

# All previously-known syntax failures have been fixed:
#   1. Replace() changed from F.expr(f'...') to F.regexp_replace (v1.5)
#   2. DLT path escaping added for backslashes (v1.5)
#   3. ODBC connection strings detected and routed to database destination (v1.5)
#   4. DLT filter @dlt.expect expressions properly escaped (v1.5)
#   5. Expression fallbacks (F.expr) now escape quotes/backslashes (v1.5)
#   6. DateTimeAdd f-string quoting fixed — pure SQL string generation (v1.5)


@pytest.fixture
def pyspark_config(tmp_path: Path) -> ConversionConfig:
    return ConversionConfig(output_dir=tmp_path, output_format=OutputFormat.PYSPARK)


@pytest.fixture
def dlt_config(tmp_path: Path) -> ConversionConfig:
    return ConversionConfig(output_dir=tmp_path, output_format=OutputFormat.DLT)


@pytest.fixture
def sql_config(tmp_path: Path) -> ConversionConfig:
    return ConversionConfig(output_dir=tmp_path, output_format=OutputFormat.SQL)


@pytest.fixture
def lakeflow_config(tmp_path: Path) -> ConversionConfig:
    return ConversionConfig(output_dir=tmp_path, output_format=OutputFormat.LAKEFLOW)


# ── Phase 1: Parsing ──────────────────────────────────────────────────


@pytest.mark.skipif(not PACKT_FILES, reason="Packt fixtures not found")
class TestPacktParsing:
    """Every Packt .yxmd file must parse without errors."""

    @pytest.mark.parametrize("yxmd", PACKT_FILES, ids=lambda p: p.stem)
    def test_parse(self, yxmd: Path) -> None:
        parser = WorkflowParser()
        parsed = parser.parse(yxmd)
        assert len(parsed.nodes) > 0, f"{yxmd.name}: no nodes parsed"
        assert len(parsed.connections) >= 0


# ── Phase 2: PySpark conversion + syntax validation ──────────────────


@pytest.mark.skipif(not PACKT_FILES, reason="Packt fixtures not found")
class TestPacktPySpark:
    """Every Packt workflow must convert to valid PySpark."""

    @pytest.fixture(autouse=True)
    def _setup(self, pyspark_config: ConversionConfig) -> None:
        self.pipeline = ConversionPipeline(pyspark_config)
        self.validator = SyntaxValidator()

    @pytest.mark.parametrize("yxmd", PACKT_FILES, ids=lambda p: p.stem)
    def test_convert_pyspark(self, yxmd: Path) -> None:
        result = self.pipeline.convert(yxmd)
        _assert_basic_result(result, yxmd)

        # Validate Python syntax
        for py_file in (f for f in result.output.files if f.file_type == "python"):
            validation = self.validator.validate_string(py_file.content, filename=py_file.filename)
            assert validation.is_valid, f"Syntax error in {py_file.filename} ({yxmd.name}): {validation.errors}"


# ── Phase 3: DLT conversion + syntax validation ─────────────────────


@pytest.mark.skipif(not PACKT_FILES, reason="Packt fixtures not found")
class TestPacktDLT:
    """Every Packt workflow must convert to valid DLT."""

    @pytest.fixture(autouse=True)
    def _setup(self, dlt_config: ConversionConfig) -> None:
        self.pipeline = ConversionPipeline(dlt_config)
        self.validator = SyntaxValidator()

    @pytest.mark.parametrize("yxmd", PACKT_FILES, ids=lambda p: p.stem)
    def test_convert_dlt(self, yxmd: Path) -> None:
        result = self.pipeline.convert(yxmd)
        _assert_basic_result(result, yxmd)

        for py_file in (f for f in result.output.files if f.file_type == "python"):
            validation = self.validator.validate_string(py_file.content, filename=py_file.filename)
            assert validation.is_valid, f"Syntax error in {py_file.filename} ({yxmd.name}): {validation.errors}"


# ── Phase 4: SQL conversion ─────────────────────────────────────────


@pytest.mark.skipif(not PACKT_FILES, reason="Packt fixtures not found")
class TestPacktSQL:
    """Every Packt workflow must produce non-empty SQL with SELECT."""

    @pytest.fixture(autouse=True)
    def _setup(self, sql_config: ConversionConfig) -> None:
        self.pipeline = ConversionPipeline(sql_config)

    @pytest.mark.parametrize("yxmd", PACKT_FILES, ids=lambda p: p.stem)
    def test_convert_sql(self, yxmd: Path) -> None:
        result = self.pipeline.convert(yxmd)
        _assert_basic_result(result, yxmd)

        sql_files = [f for f in result.output.files if f.file_type == "sql"]
        assert sql_files, f"{yxmd.name}: no SQL output"
        for sql_file in sql_files:
            assert sql_file.content.strip(), f"Empty SQL for {yxmd.name}"
            assert "SELECT" in sql_file.content, f"No SELECT in SQL for {yxmd.name}"


# ── Phase 5: Lakeflow conversion ────────────────────────────────────


@pytest.mark.skipif(not PACKT_FILES, reason="Packt fixtures not found")
class TestPacktLakeflow:
    """Every Packt workflow must produce valid Lakeflow output."""

    @pytest.fixture(autouse=True)
    def _setup(self, lakeflow_config: ConversionConfig) -> None:
        self.pipeline = ConversionPipeline(lakeflow_config)

    @pytest.mark.parametrize("yxmd", PACKT_FILES, ids=lambda p: p.stem)
    def test_convert_lakeflow(self, yxmd: Path) -> None:
        result = self.pipeline.convert(yxmd)
        _assert_basic_result(result, yxmd)

        sql_files = [f for f in result.output.files if f.file_type == "sql"]
        assert sql_files, f"{yxmd.name}: no Lakeflow output"
        for sql_file in sql_files:
            content = sql_file.content.strip()
            assert content, f"Empty Lakeflow for {yxmd.name}"
            assert "CREATE OR REFRESH" in content, f"No CREATE OR REFRESH for {yxmd.name}"


# ── Phase 6: Confidence & coverage quality gates ─────────────────────


@pytest.mark.skipif(not PACKT_FILES, reason="Packt fixtures not found")
class TestPacktQuality:
    """Quality assertions across the full Packt corpus."""

    def test_corpus_average_coverage(self, pyspark_config: ConversionConfig) -> None:
        """The average coverage across all Packt workflows must be >= 70%."""
        pipeline = ConversionPipeline(pyspark_config)
        coverages = []
        for yxmd in PACKT_FILES:
            result = pipeline.convert(yxmd)
            stats = result.output.stats
            total = stats.get("total_nodes", 0)
            supported = stats.get("supported_nodes", 0)
            if total > 0:
                coverages.append(supported / total * 100)

        avg = sum(coverages) / len(coverages) if coverages else 0
        assert avg >= 70, f"Average corpus coverage {avg:.1f}% is below 70% threshold"

    def test_no_conversion_crashes(self, pyspark_config: ConversionConfig) -> None:
        """Every file must convert without raising an exception."""
        pipeline = ConversionPipeline(pyspark_config)
        failures = []
        for yxmd in PACKT_FILES:
            try:
                pipeline.convert(yxmd)
            except Exception as e:
                failures.append(f"{yxmd.name}: {type(e).__name__}: {e}")

        assert not failures, f"{len(failures)} conversion failures:\n" + "\n".join(failures)


# ── Helpers ──────────────────────────────────────────────────────────


def _assert_basic_result(result: ConversionResult, yxmd: Path) -> None:
    """Common assertions for any conversion result."""
    assert isinstance(result, ConversionResult)
    assert result.dag.node_count > 0, f"{yxmd.name}: empty DAG"
    assert len(result.output.files) > 0, f"{yxmd.name}: no output files"
