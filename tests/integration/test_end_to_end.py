"""End-to-end integration tests for the conversion pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from a2d.config import ConversionConfig, OutputFormat
from a2d.pipeline import ConversionPipeline, ConversionResult
from a2d.validation.syntax_validator import SyntaxValidator

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
WORKFLOWS_DIR = FIXTURES_DIR / "workflows"
DEMO_DIR = Path(__file__).parent.parent.parent / "demo"


@pytest.fixture
def pyspark_config(tmp_path: Path) -> ConversionConfig:
    return ConversionConfig(
        output_dir=tmp_path,
        output_format=OutputFormat.PYSPARK,
        generate_orchestration=True,
    )


@pytest.fixture
def dlt_config(tmp_path: Path) -> ConversionConfig:
    return ConversionConfig(
        output_dir=tmp_path,
        output_format=OutputFormat.DLT,
        generate_orchestration=False,
    )


@pytest.fixture
def sql_config(tmp_path: Path) -> ConversionConfig:
    return ConversionConfig(
        output_dir=tmp_path,
        output_format=OutputFormat.SQL,
        generate_orchestration=False,
    )


@pytest.fixture
def lakeflow_config(tmp_path: Path) -> ConversionConfig:
    return ConversionConfig(
        output_dir=tmp_path,
        output_format=OutputFormat.LAKEFLOW,
        generate_orchestration=False,
    )


class TestConvertSimpleFilter:
    """Test full pipeline conversion of simple_filter.yxmd."""

    def test_convert_simple_filter_pyspark(self, pyspark_config: ConversionConfig) -> None:
        pipeline = ConversionPipeline(pyspark_config)
        result = pipeline.convert(WORKFLOWS_DIR / "simple_filter.yxmd")

        assert isinstance(result, ConversionResult)
        assert result.dag.node_count == 4
        assert result.dag.edge_count == 3
        assert result.parsed_workflow.alteryx_version == "2023.1"

        # Check generated files
        assert len(result.output.files) >= 1
        py_files = [f for f in result.output.files if f.file_type == "python"]
        assert len(py_files) >= 1
        assert "simple_filter" in py_files[0].filename

        # Check content has expected elements
        content = py_files[0].content
        assert "spark" in content.lower() or "df_" in content
        assert "filter" in content.lower() or "Filter" in content

    def test_convert_simple_filter_generates_orchestration(self, pyspark_config: ConversionConfig) -> None:
        pipeline = ConversionPipeline(pyspark_config)
        result = pipeline.convert(WORKFLOWS_DIR / "simple_filter.yxmd")

        json_files = [f for f in result.output.files if f.file_type == "json"]
        assert len(json_files) >= 1
        assert "workflow" in json_files[0].filename.lower()
        assert "a2d_simple_filter" in json_files[0].content

    def test_convert_simple_filter_dlt(self, dlt_config: ConversionConfig) -> None:
        pipeline = ConversionPipeline(dlt_config)
        result = pipeline.convert(WORKFLOWS_DIR / "simple_filter.yxmd")

        assert len(result.output.files) >= 1
        py_files = [f for f in result.output.files if f.file_type == "python"]
        assert len(py_files) >= 1
        content = py_files[0].content
        assert "dlt" in content.lower()

    def test_convert_simple_filter_sql(self, sql_config: ConversionConfig) -> None:
        pipeline = ConversionPipeline(sql_config)
        result = pipeline.convert(WORKFLOWS_DIR / "simple_filter.yxmd")

        assert len(result.output.files) >= 1
        sql_files = [f for f in result.output.files if f.file_type == "sql"]
        assert len(sql_files) >= 1
        content = sql_files[0].content
        assert "WITH" in content or "SELECT" in content

    def test_convert_simple_filter_lakeflow(self, lakeflow_config: ConversionConfig) -> None:
        pipeline = ConversionPipeline(lakeflow_config)
        result = pipeline.convert(WORKFLOWS_DIR / "simple_filter.yxmd")

        assert len(result.output.files) >= 1
        sql_files = [f for f in result.output.files if f.file_type == "sql"]
        assert len(sql_files) >= 1
        content = sql_files[0].content
        assert "CREATE OR REFRESH" in content
        assert "LIVE." in content
        # Should NOT have CTE-style WITH
        non_comment_lines = [l.strip() for l in content.split("\n") if l.strip() and not l.strip().startswith("--")]
        assert not any(l.startswith("WITH ") for l in non_comment_lines)


class TestConvertJoinSummarize:
    """Test full pipeline for join_and_summarize.yxmd."""

    def test_convert_join_summarize(self, pyspark_config: ConversionConfig) -> None:
        pipeline = ConversionPipeline(pyspark_config)
        result = pipeline.convert(WORKFLOWS_DIR / "join_and_summarize.yxmd")

        assert result.dag.node_count == 5
        assert result.dag.edge_count == 4

        py_files = [f for f in result.output.files if f.file_type == "python"]
        assert len(py_files) >= 1
        content = py_files[0].content

        # Should contain join and summarize related code
        assert "join" in content.lower() or "Join" in content
        assert "groupBy" in content or "group_by" in content.lower() or "agg" in content


class TestConvertJoinSummarizeLakeflow:
    """Test Lakeflow format for join_and_summarize.yxmd."""

    def test_convert_join_summarize_lakeflow(self, lakeflow_config: ConversionConfig) -> None:
        pipeline = ConversionPipeline(lakeflow_config)
        result = pipeline.convert(WORKFLOWS_DIR / "join_and_summarize.yxmd")

        assert result.dag.node_count == 5
        sql_files = [f for f in result.output.files if f.file_type == "sql"]
        assert len(sql_files) >= 1
        content = sql_files[0].content
        assert "CREATE OR REFRESH" in content
        assert "LIVE." in content
        assert "JOIN" in content.upper() or "GROUP BY" in content


class TestConvertComplexPipelineLakeflow:
    """Test Lakeflow format for complex_pipeline.yxmd."""

    def test_convert_complex_pipeline_lakeflow(self, lakeflow_config: ConversionConfig) -> None:
        pipeline = ConversionPipeline(lakeflow_config)
        result = pipeline.convert(WORKFLOWS_DIR / "complex_pipeline.yxmd")

        assert result.dag.node_count == 8
        sql_files = [f for f in result.output.files if f.file_type == "sql"]
        assert len(sql_files) >= 1
        content = sql_files[0].content
        assert "CREATE OR REFRESH" in content
        assert "LIVE." in content


class TestConvertComplexPipeline:
    """Test full pipeline for complex_pipeline.yxmd."""

    def test_convert_complex_pipeline(self, pyspark_config: ConversionConfig) -> None:
        pipeline = ConversionPipeline(pyspark_config)
        result = pipeline.convert(WORKFLOWS_DIR / "complex_pipeline.yxmd")

        assert result.dag.node_count == 8
        assert result.dag.edge_count == 7

        py_files = [f for f in result.output.files if f.file_type == "python"]
        assert len(py_files) >= 1
        content = py_files[0].content

        # Should contain formula, filter, select, sort, unique, summarize
        assert "withColumn" in content or "formula" in content.lower()
        assert "filter" in content.lower() or "Filter" in content

    def test_complex_pipeline_has_topological_order(self, pyspark_config: ConversionConfig) -> None:
        pipeline = ConversionPipeline(pyspark_config)
        result = pipeline.convert(WORKFLOWS_DIR / "complex_pipeline.yxmd")

        ordered = result.dag.topological_order()
        assert len(ordered) == 8
        # First should be TextInput (node 1), last should be Output (node 8)
        assert ordered[0].node_id == 1
        assert ordered[-1].node_id == 8


class TestBatchConvert:
    """Test batch conversion of all workflow fixtures."""

    def test_batch_convert(self, pyspark_config: ConversionConfig) -> None:
        pipeline = ConversionPipeline(pyspark_config)
        results = pipeline.convert_batch(WORKFLOWS_DIR)

        assert len(results) == 3  # simple_filter, join_and_summarize, complex_pipeline

        for result in results:
            assert isinstance(result, ConversionResult)
            assert result.dag.node_count > 0
            assert len(result.output.files) > 0


class TestGeneratedCodeSyntax:
    """Verify all generated code passes Python ast.parse()."""

    def test_generated_pyspark_syntax(self, pyspark_config: ConversionConfig) -> None:
        pipeline = ConversionPipeline(pyspark_config)
        validator = SyntaxValidator()

        for yxmd in sorted(WORKFLOWS_DIR.glob("*.yxmd")):
            result = pipeline.convert(yxmd)
            py_files = [f for f in result.output.files if f.file_type == "python"]
            for py_file in py_files:
                validation = validator.validate_string(py_file.content, filename=py_file.filename)
                assert validation.is_valid, (
                    f"Syntax error in {py_file.filename} (from {yxmd.name}): {validation.errors}"
                )

    def test_generated_dlt_syntax(self, dlt_config: ConversionConfig) -> None:
        pipeline = ConversionPipeline(dlt_config)
        validator = SyntaxValidator()

        for yxmd in sorted(WORKFLOWS_DIR.glob("*.yxmd")):
            result = pipeline.convert(yxmd)
            py_files = [f for f in result.output.files if f.file_type == "python"]
            for py_file in py_files:
                validation = validator.validate_string(py_file.content, filename=py_file.filename)
                assert validation.is_valid, (
                    f"Syntax error in {py_file.filename} (from {yxmd.name}): {validation.errors}"
                )

    def test_generated_sql_is_nonempty(self, sql_config: ConversionConfig) -> None:
        pipeline = ConversionPipeline(sql_config)

        for yxmd in sorted(WORKFLOWS_DIR.glob("*.yxmd")):
            result = pipeline.convert(yxmd)
            sql_files = [f for f in result.output.files if f.file_type == "sql"]
            for sql_file in sql_files:
                assert len(sql_file.content.strip()) > 0, f"Empty SQL output for {yxmd.name}"
                assert "SELECT" in sql_file.content, f"No SELECT in SQL for {yxmd.name}"

    def test_generated_lakeflow_is_valid(self, lakeflow_config: ConversionConfig) -> None:
        pipeline = ConversionPipeline(lakeflow_config)

        for yxmd in sorted(WORKFLOWS_DIR.glob("*.yxmd")):
            result = pipeline.convert(yxmd)
            sql_files = [f for f in result.output.files if f.file_type == "sql"]
            for sql_file in sql_files:
                content = sql_file.content.strip()
                assert len(content) > 0, f"Empty Lakeflow output for {yxmd.name}"
                assert "CREATE OR REFRESH" in content, f"No CREATE OR REFRESH in Lakeflow for {yxmd.name}"
                assert "LIVE." in content or result.dag.node_count == 1, (
                    f"No LIVE. references in Lakeflow for {yxmd.name}"
                )


# ═══════════════════════════════════════════════════════════════════════════
# Demo workflow integration tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not DEMO_DIR.exists(), reason="Demo directory not found")
class TestDemoWorkflowsPySpark:
    """Parse → IR → PySpark for all demo workflows."""

    @pytest.fixture(autouse=True)
    def _setup(self, pyspark_config: ConversionConfig) -> None:
        self.pipeline = ConversionPipeline(pyspark_config)
        self.validator = SyntaxValidator()

    @pytest.mark.parametrize(
        "demo_file", sorted(DEMO_DIR.glob("*.yxmd")) if DEMO_DIR.exists() else [], ids=lambda p: p.stem
    )
    def test_demo_converts_pyspark(self, demo_file: Path) -> None:
        result = self.pipeline.convert(demo_file)
        assert result.dag.node_count > 0, f"{demo_file.name}: empty DAG"
        assert len(result.output.files) > 0, f"{demo_file.name}: no output files"

        py_files = [f for f in result.output.files if f.file_type == "python"]
        assert len(py_files) >= 1, f"{demo_file.name}: no Python output"

        for py_file in py_files:
            validation = self.validator.validate_string(py_file.content, filename=py_file.filename)
            assert validation.is_valid, (
                f"Syntax error in {py_file.filename} (from {demo_file.name}): {validation.errors}"
            )


@pytest.mark.skipif(not DEMO_DIR.exists(), reason="Demo directory not found")
class TestDemoWorkflowsDLT:
    """Parse → IR → DLT for all demo workflows."""

    @pytest.fixture(autouse=True)
    def _setup(self, dlt_config: ConversionConfig) -> None:
        self.pipeline = ConversionPipeline(dlt_config)
        self.validator = SyntaxValidator()

    @pytest.mark.parametrize(
        "demo_file", sorted(DEMO_DIR.glob("*.yxmd")) if DEMO_DIR.exists() else [], ids=lambda p: p.stem
    )
    def test_demo_converts_dlt(self, demo_file: Path) -> None:
        result = self.pipeline.convert(demo_file)
        assert result.dag.node_count > 0, f"{demo_file.name}: empty DAG"

        py_files = [f for f in result.output.files if f.file_type == "python"]
        assert len(py_files) >= 1, f"{demo_file.name}: no Python output"

        for py_file in py_files:
            validation = self.validator.validate_string(py_file.content, filename=py_file.filename)
            assert validation.is_valid, (
                f"Syntax error in {py_file.filename} (from {demo_file.name}): {validation.errors}"
            )


@pytest.mark.skipif(not DEMO_DIR.exists(), reason="Demo directory not found")
class TestDemoWorkflowsSQL:
    """Parse → IR → SQL for all demo workflows."""

    @pytest.fixture(autouse=True)
    def _setup(self, sql_config: ConversionConfig) -> None:
        self.pipeline = ConversionPipeline(sql_config)

    @pytest.mark.parametrize(
        "demo_file", sorted(DEMO_DIR.glob("*.yxmd")) if DEMO_DIR.exists() else [], ids=lambda p: p.stem
    )
    def test_demo_converts_sql(self, demo_file: Path) -> None:
        result = self.pipeline.convert(demo_file)
        assert result.dag.node_count > 0, f"{demo_file.name}: empty DAG"

        sql_files = [f for f in result.output.files if f.file_type == "sql"]
        assert len(sql_files) >= 1, f"{demo_file.name}: no SQL output"

        for sql_file in sql_files:
            content = sql_file.content.strip()
            assert len(content) > 0, f"Empty SQL for {demo_file.name}"
            assert "SELECT" in content, f"No SELECT in SQL for {demo_file.name}"


@pytest.mark.skipif(not DEMO_DIR.exists(), reason="Demo directory not found")
class TestAdvancedMLPipeline:
    """Specific tests for demo/11_advanced_ml_pipeline.yxmd."""

    def test_ml_pipeline_pyspark_has_ml_constructs(self, pyspark_config: ConversionConfig) -> None:
        ml_file = DEMO_DIR / "11_advanced_ml_pipeline.yxmd"
        if not ml_file.exists():
            pytest.skip("ML pipeline demo not found")

        pipeline = ConversionPipeline(pyspark_config)
        result = pipeline.convert(ml_file)

        assert result.dag.node_count == 9  # TextInput + 4 ML tools + 4 Browse
        assert result.dag.edge_count == 8

        py_files = [f for f in result.output.files if f.file_type == "python"]
        content = py_files[0].content

        # Should have ML tool references in passthrough comments
        assert "BoostedModel" in content
        assert "NaiveBayes" in content
        assert "KCentroids" in content
        assert "PrincipalComponents" in content


@pytest.mark.skipif(not DEMO_DIR.exists(), reason="Demo directory not found")
class TestDemoWorkflowsLakeflow:
    """Parse → IR → Lakeflow for all demo workflows."""

    @pytest.fixture(autouse=True)
    def _setup(self, lakeflow_config: ConversionConfig) -> None:
        self.pipeline = ConversionPipeline(lakeflow_config)

    @pytest.mark.parametrize(
        "demo_file", sorted(DEMO_DIR.glob("*.yxmd")) if DEMO_DIR.exists() else [], ids=lambda p: p.stem
    )
    def test_demo_converts_lakeflow(self, demo_file: Path) -> None:
        result = self.pipeline.convert(demo_file)
        assert result.dag.node_count > 0, f"{demo_file.name}: empty DAG"

        sql_files = [f for f in result.output.files if f.file_type == "sql"]
        assert len(sql_files) >= 1, f"{demo_file.name}: no SQL output"

        for sql_file in sql_files:
            content = sql_file.content.strip()
            assert len(content) > 0, f"Empty Lakeflow output for {demo_file.name}"
            assert "CREATE OR REFRESH" in content, f"No CREATE OR REFRESH for {demo_file.name}"
