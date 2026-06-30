"""Main conversion pipeline orchestrating Parse -> Convert -> Build DAG -> Generate Code."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from a2d.config import ConversionConfig, OutputFormat
from a2d.converters.registry import ConverterRegistry
from a2d.exceptions import A2dError
from a2d.generators.base import CodeGenerator, GeneratedOutput
from a2d.generators.dlt import DLTGenerator
from a2d.generators.lakeflow import LakeflowGenerator
from a2d.generators.pyspark import PySparkGenerator
from a2d.generators.sql import SQLGenerator
from a2d.generators.workflow_json import WorkflowJsonGenerator
from a2d.ir.graph import WorkflowDAG
from a2d.observability.confidence import ConfidenceScore, ConfidenceScorer
from a2d.observability.expression_audit import ExpressionAuditEntry
from a2d.observability.performance_hints import PerformanceHint
from a2d.parser.schema import ParsedWorkflow
from a2d.parser.workflow_parser import WorkflowParser

logger = logging.getLogger("a2d.pipeline")


@dataclass
class ConversionResult:
    """Result of converting a single Alteryx workflow."""

    output: GeneratedOutput
    dag: WorkflowDAG
    parsed_workflow: ParsedWorkflow
    warnings: list[str] = field(default_factory=list)
    confidence: ConfidenceScore | None = None
    expression_audit: list[ExpressionAuditEntry] | None = None
    performance_hints: list[PerformanceHint] | None = None


@dataclass
class FormatConversionResult:
    """Per-format conversion result inside a multi-format conversion."""

    format: str  # "pyspark" | "dlt" | "sql" | "lakeflow"
    status: str  # "success" | "failed"
    output: GeneratedOutput | None  # None when failed
    warnings: list[str] = field(default_factory=list)
    confidence: ConfidenceScore | None = None
    error: str | None = None  # message when failed
    # Per-format wall-clock duration for the generator + post-processing only
    # (does NOT include the shared parse / DAG-build / validation cost). Stays
    # at 0.0 for results that are constructed elsewhere (e.g. test fixtures).
    duration_ms: float = 0.0


@dataclass
class MultiFormatConversionResult:
    """Result of converting a single Alteryx workflow into all output formats."""

    parsed_workflow: ParsedWorkflow
    dag: WorkflowDAG
    warnings: list[str] = field(default_factory=list)  # DAG validation only
    formats: dict[str, FormatConversionResult] = field(default_factory=dict)
    best_format: str = ""  # "pyspark" | ... | "" if all failed
    expression_audit: list[ExpressionAuditEntry] | None = None
    performance_hints: list[PerformanceHint] | None = None


# Node types to exclude from the DAG (visual-only, no data transformation)
_SKIP_TYPES = frozenset({"ToolContainer", "Tab"})

# Tiebreak ordering for best_format selection (highest priority first)
_FORMAT_PRIORITY: tuple[str, ...] = ("pyspark", "dlt", "sql", "lakeflow")

# Generator class registry — used by both convert() and convert_all_formats()
_GENERATOR_CLASSES: dict[OutputFormat, type[CodeGenerator]] = {
    OutputFormat.PYSPARK: PySparkGenerator,
    OutputFormat.DLT: DLTGenerator,
    OutputFormat.SQL: SQLGenerator,
    OutputFormat.LAKEFLOW: LakeflowGenerator,
}


class ConversionPipeline:
    """Main orchestration: Parse -> Convert -> Build DAG -> Generate Code."""

    def __init__(self, config: ConversionConfig) -> None:
        self.config = config
        self._parser = WorkflowParser()

    def convert(self, path: Path) -> ConversionResult:
        """Convert a single .yxmd file."""
        # 1. Parse XML
        parsed = self._parser.parse(path)

        # 2. Build IR DAG
        dag = self._build_dag(parsed)

        # 3. Validate DAG
        validation_issues = dag.validate()

        # 4. Generate code
        generator = self._get_generator()
        workflow_name = path.stem

        # Pre-score confidence so generators can embed it in headers
        scorer = ConfidenceScorer()
        confidence = scorer.score(dag, GeneratedOutput())  # pre-score from DAG alone

        generator.metadata = {
            "confidence": confidence,
        }
        output = generator.generate(dag, workflow_name)

        # Now update metadata stats from the actual output for the result
        generator.metadata["stats"] = output.stats

        # 5. Generate orchestration if configured
        if self.config.generate_orchestration:
            wf_gen = WorkflowJsonGenerator(self.config)
            wf_output = wf_gen.generate(dag, workflow_name)
            output.files.extend(wf_output.files)

        warnings = validation_issues + output.warnings

        # 6. Score conversion confidence (re-score with actual output)
        confidence = scorer.score(dag, output)

        # 7. Expression audit (optional)
        expression_audit = None
        if self.config.include_expression_audit:
            from a2d.observability.expression_audit import ExpressionAuditor

            auditor = ExpressionAuditor()
            expression_audit = auditor.audit(dag, output)

        # 8. Performance hints (optional)
        performance_hints = None
        if self.config.include_performance_hints:
            from a2d.observability.performance_hints import PerformanceAnalyzer

            analyzer = PerformanceAnalyzer()
            performance_hints = analyzer.analyze(dag)

        return ConversionResult(
            output=output,
            dag=dag,
            parsed_workflow=parsed,
            warnings=warnings,
            confidence=confidence,
            expression_audit=expression_audit,
            performance_hints=performance_hints,
        )

    def convert_batch(self, directory: Path) -> list[ConversionResult]:
        """Convert all .yxmd files in a directory.

        Failed files are logged as errors. Use the batch orchestrator for
        structured error tracking.
        """
        results = []
        for path in sorted(directory.glob("**/*.yxmd")):
            try:
                result = self.convert(path)
                results.append(result)
            except A2dError as e:
                logger.error("Failed to convert %s: %s", path, e)
            except Exception as e:
                logger.error("Unexpected error converting %s: %s", path, e)
        if not results:
            logger.warning("No workflows were successfully converted from %s", directory)
        return results

    def _build_dag(self, parsed: ParsedWorkflow) -> WorkflowDAG:
        """Build an IR DAG from a parsed workflow."""
        dag = WorkflowDAG()
        # Node types to exclude from the DAG (visual-only, no data transformation)

        disabled_ids: set[int] = set()
        for node in parsed.nodes:
            if node.disabled:
                disabled_ids.add(node.tool_id)
                logger.info("Skipping disabled node %d (%s)", node.tool_id, node.tool_type)
                continue
            if node.tool_type in _SKIP_TYPES:
                logger.debug("Skipping visual-only node %d (%s)", node.tool_id, node.tool_type)
                continue
            ir_node = ConverterRegistry.convert_node(node, self.config)
            dag.add_node(ir_node)

        node_ids = set(dag.all_node_ids())
        for conn in parsed.connections:
            src, dst = conn.origin.tool_id, conn.destination.tool_id
            if src not in node_ids or dst not in node_ids:
                if src not in disabled_ids and dst not in disabled_ids:
                    missing = [nid for nid in (src, dst) if nid not in node_ids]
                    logger.warning(
                        "Skipping edge %d→%d: node(s) %s not in graph",
                        src,
                        dst,
                        missing,
                    )
                continue
            dag.add_edge(
                src,
                dst,
                conn.origin.anchor_name,
                conn.destination.anchor_name,
            )
        return dag

    def _get_generator(self) -> CodeGenerator:
        """Return the appropriate code generator for the configured output format."""
        gen_class = _GENERATOR_CLASSES[self.config.output_format]
        return gen_class(self.config)

    def convert_all_formats(self, path: Path) -> MultiFormatConversionResult:
        """Convert a single .yxmd file into all four output formats.

        Parses + builds DAG + validates ONCE, then runs each generator.
        Per-format failures are isolated: one failure does not abort the others.
        Format-agnostic enrichments (expression_audit, performance_hints) are
        computed once.

        Orchestration JSON (workflow_json) is appended to every successful
        format's files so each download is self-contained.
        """
        # 1. Parse XML (once)
        parsed = self._parser.parse(path)

        # 2. Build IR DAG (once)
        dag = self._build_dag(parsed)

        # 3. Validate DAG (once) — these warnings are format-agnostic
        validation_issues = list(dag.validate())

        workflow_name = path.stem

        # 4. Pre-score confidence so generators can embed it in headers
        scorer = ConfidenceScorer()
        pre_score = scorer.score(dag, GeneratedOutput())

        # 5. Run each generator independently, capturing failures
        format_results: dict[str, FormatConversionResult] = {}
        for fmt in (OutputFormat.PYSPARK, OutputFormat.DLT, OutputFormat.SQL, OutputFormat.LAKEFLOW):
            fmt_key = fmt.value
            t_fmt = time.monotonic()
            try:
                gen_class = _GENERATOR_CLASSES[fmt]
                # Generators read self.config.output_format implicitly in some places,
                # but accept the shared config; pass it as-is. The generator class
                # determines the format, not the config field.
                generator = gen_class(self.config)
                generator.metadata = {"confidence": pre_score}
                output = generator.generate(dag, workflow_name)
                generator.metadata["stats"] = output.stats

                # Append orchestration JSON if configured (once per format)
                if self.config.generate_orchestration:
                    try:
                        wf_gen = WorkflowJsonGenerator(self.config)
                        wf_output = wf_gen.generate(dag, workflow_name)
                        output.files.extend(wf_output.files)
                    except Exception as wf_exc:  # pragma: no cover - defensive
                        logger.warning("Orchestration JSON generation failed for %s: %s", fmt_key, wf_exc)

                # Re-score confidence using the actual output
                fmt_confidence = scorer.score(dag, output)

                duration_ms = (time.monotonic() - t_fmt) * 1000.0
                format_results[fmt_key] = FormatConversionResult(
                    format=fmt_key,
                    status="success",
                    output=output,
                    warnings=list(output.warnings),
                    confidence=fmt_confidence,
                    error=None,
                    duration_ms=duration_ms,
                )
            except Exception as exc:  # per-format isolation
                logger.exception("Generator failed for format %s on %s", fmt_key, path)
                duration_ms = (time.monotonic() - t_fmt) * 1000.0
                format_results[fmt_key] = FormatConversionResult(
                    format=fmt_key,
                    status="failed",
                    output=None,
                    warnings=[],
                    confidence=None,
                    error=str(exc),
                    duration_ms=duration_ms,
                )

        # 6. Determine best_format (highest confidence among successful, tiebreak by priority)
        best_format = ""
        best_score: float = -1.0
        for fmt_key in _FORMAT_PRIORITY:
            r = format_results.get(fmt_key)
            if r is None or r.status != "success" or r.confidence is None:
                continue
            score = r.confidence.overall
            if score > best_score:
                best_score = score
                best_format = fmt_key

        # 7. Expression audit (once, format-agnostic — uses any successful output for warnings)
        expression_audit = None
        if self.config.include_expression_audit:
            try:
                from a2d.observability.expression_audit import ExpressionAuditor

                # Use the first successful output for warning context, else empty
                ref_output: GeneratedOutput | None = None
                for fmt_key in _FORMAT_PRIORITY:
                    r = format_results.get(fmt_key)
                    if r and r.status == "success" and r.output is not None:
                        ref_output = r.output
                        break
                auditor = ExpressionAuditor()
                expression_audit = auditor.audit(dag, ref_output or GeneratedOutput())
            except Exception:  # pragma: no cover - defensive
                logger.exception("Expression audit failed")
                expression_audit = None

        # 8. Performance hints (once, format-agnostic)
        performance_hints = None
        if self.config.include_performance_hints:
            try:
                from a2d.observability.performance_hints import PerformanceAnalyzer

                analyzer = PerformanceAnalyzer()
                performance_hints = analyzer.analyze(dag)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Performance hints analysis failed")
                performance_hints = None

        return MultiFormatConversionResult(
            parsed_workflow=parsed,
            dag=dag,
            warnings=validation_issues,
            formats=format_results,
            best_format=best_format,
            expression_audit=expression_audit,
            performance_hints=performance_hints,
        )
