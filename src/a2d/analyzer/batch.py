"""Batch analysis of multiple Alteryx workflow files."""

from __future__ import annotations

import logging
from pathlib import Path

from a2d.analyzer.complexity import ComplexityAnalyzer
from a2d.analyzer.coverage import CoverageAnalyzer
from a2d.analyzer.readiness import ReadinessAssessor, WorkflowAnalysis
from a2d.config import ConversionConfig
from a2d.exceptions import A2dError
from a2d.ir.graph import WorkflowDAG
from a2d.parser.schema import ParsedWorkflow
from a2d.parser.workflow_parser import WorkflowParser

logger = logging.getLogger("a2d.analyzer.batch")


class BatchAnalyzer:
    """Analyze multiple workflow files for migration readiness.

    ``expand_macros`` inlines referenced ``.yxmc`` macros into each workflow's DAG
    before analysis — the same step the conversion pipeline runs. It is off by
    default so CLI/existing behavior is unchanged, but the hosted App enables it so
    a ``.yxzp`` (which extracts its macros co-located) analyzes the macro's real
    interior instead of classifying the macro-call node as an unsupported Unknown.
    Unresolvable macros are left in place, so this never fails a workflow.
    ``macro_search_paths`` are extra directories to find macros in, besides each
    workflow's own (e.g. a migration project's shared ``.yxmc`` files).
    """

    def __init__(self, *, expand_macros: bool = False, macro_search_paths: list[Path] | None = None) -> None:
        self._parser = WorkflowParser()
        self._complexity_analyzer = ComplexityAnalyzer()
        self._coverage_analyzer = CoverageAnalyzer()
        self._readiness_assessor = ReadinessAssessor()
        self._expand_macros = expand_macros
        self._macro_search_paths = list(macro_search_paths or [])

    def analyze_files(self, paths: list[Path]) -> list[WorkflowAnalysis]:
        """Analyze multiple workflow files and return analysis results."""
        results: list[WorkflowAnalysis] = []

        for path in paths:
            try:
                analysis = self._analyze_single(path)
                results.append(analysis)
            except A2dError as e:
                logger.error("Failed to analyze %s: %s", path, e)

        return results

    def build_dag(self, parsed: ParsedWorkflow) -> WorkflowDAG:
        """Build the IR DAG the conversion pipeline builds for this workflow.

        Same builder as Convert (disabled tools and visual-only containers
        dropped, macros expanded when enabled), so an assessment counts the same
        tools a conversion does. Shared by single-file analysis and the portfolio
        pass so both walk the same graph without re-parsing.
        """
        from a2d.pipeline import ConversionPipeline

        config = ConversionConfig(expand_macros=self._expand_macros, macro_search_paths=tuple(self._macro_search_paths))
        try:
            return ConversionPipeline(config).build_dag(parsed)
        except Exception as exc:  # never let macro expansion break analysis
            if not self._expand_macros:
                raise
            logger.warning("Macro expansion skipped for %s: %s", parsed.file_path, exc)
            return ConversionPipeline(ConversionConfig()).build_dag(parsed)

    def analyze_workflow(self, parsed: ParsedWorkflow, dag: WorkflowDAG) -> WorkflowAnalysis:
        """Run complexity/coverage/readiness on an already-built DAG."""
        return self._assess(parsed, dag)

    def _analyze_single(self, path: Path) -> WorkflowAnalysis:
        """Analyze a single workflow file."""
        parsed = self._parser.parse(path)
        dag = self.build_dag(parsed)
        return self._assess(parsed, dag)

    def _assess(self, parsed: ParsedWorkflow, dag: WorkflowDAG) -> WorkflowAnalysis:
        """Compute the analysis for a parsed workflow and its DAG."""
        path = Path(parsed.file_path)

        # Run analyses
        complexity = self._complexity_analyzer.analyze(dag, parsed.macro_references)
        coverage = self._coverage_analyzer.analyze_dag(dag)

        # Assess readiness
        priority, effort = self._readiness_assessor.assess(complexity, coverage)

        # Collect validation warnings
        warnings = dag.validate()

        # Collect tool types used
        tool_types_used: set[str] = set()
        for node in dag.all_nodes():
            tool_type = node.original_tool_type or type(node).__name__.replace("Node", "")
            tool_types_used.add(tool_type)

        return WorkflowAnalysis(
            file_path=str(path),
            workflow_name=path.stem,
            complexity=complexity,
            coverage=coverage,
            node_count=dag.node_count,
            connection_count=dag.edge_count,
            tool_types_used=tool_types_used,
            warnings=warnings,
            migration_priority=priority,
            estimated_effort=effort,
        )
