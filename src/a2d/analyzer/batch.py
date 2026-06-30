"""Batch analysis of multiple Alteryx workflow files."""

from __future__ import annotations

import logging
from pathlib import Path

from a2d.analyzer.complexity import ComplexityAnalyzer
from a2d.analyzer.coverage import CoverageAnalyzer
from a2d.analyzer.readiness import ReadinessAssessor, WorkflowAnalysis
from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry
from a2d.exceptions import A2dError
from a2d.ir.graph import WorkflowDAG
from a2d.parser.workflow_parser import WorkflowParser

logger = logging.getLogger("a2d.analyzer.batch")


class BatchAnalyzer:
    """Analyze multiple workflow files for migration readiness."""

    def __init__(self) -> None:
        self._parser = WorkflowParser()
        self._complexity_analyzer = ComplexityAnalyzer()
        self._coverage_analyzer = CoverageAnalyzer()
        self._readiness_assessor = ReadinessAssessor()

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

    def _analyze_single(self, path: Path) -> WorkflowAnalysis:
        """Analyze a single workflow file."""
        # Parse the workflow
        parsed = self._parser.parse(path)

        # Build the IR DAG using default config
        config = ConversionConfig()
        dag = WorkflowDAG()
        for node in parsed.nodes:
            ir_node = ConverterRegistry.convert_node(node, config)
            dag.add_node(ir_node)
        node_ids = set(dag.all_node_ids())
        for conn in parsed.connections:
            src, dst = conn.origin.tool_id, conn.destination.tool_id
            if src not in node_ids or dst not in node_ids:
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
