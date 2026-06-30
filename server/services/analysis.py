"""Analysis service — wraps BatchAnalyzer."""

from __future__ import annotations

import logging
import tempfile
from collections import Counter
from pathlib import Path

from a2d.analyzer.batch import BatchAnalyzer
from server.utils.validation import sanitize_filename

logger = logging.getLogger("a2d.server.services.analysis")


def analyze_files(files: list[tuple[str, bytes]]) -> dict:
    """Analyze uploaded .yxmd files and return analysis dict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        paths: list[Path] = []
        for filename, content in files:
            p = Path(tmpdir) / sanitize_filename(filename)
            p.write_bytes(content)
            paths.append(p)

        analyzer = BatchAnalyzer()
        analyses = analyzer.analyze_files(paths)

    total = len(analyses)
    if total == 0:
        return {
            "total_workflows": 0,
            "total_nodes": 0,
            "avg_coverage": 0.0,
            "avg_complexity": 0.0,
            "workflows": [],
            "tool_frequency": {},
            "unsupported_tools": [],
        }

    avg_coverage = sum(a.coverage.coverage_percentage for a in analyses) / total
    avg_complexity = sum(a.complexity.total_score for a in analyses) / total
    total_nodes = sum(a.node_count for a in analyses)

    tool_counter: Counter = Counter()
    unsupported: set[str] = set()
    for a in analyses:
        for tool_type, count in a.coverage.per_tool_counts.items():
            tool_counter[tool_type] += count
        unsupported.update(a.coverage.unsupported_types)

    workflows = [
        {
            "file_name": Path(a.file_path).name,
            "workflow_name": a.workflow_name,
            "node_count": a.node_count,
            "connection_count": a.connection_count,
            "coverage_percentage": a.coverage.coverage_percentage,
            "complexity_score": a.complexity.total_score,
            "complexity_level": a.complexity.level,
            "migration_priority": a.migration_priority,
            "estimated_effort": a.estimated_effort,
            "tool_types": sorted(a.tool_types_used),
            "unsupported_types": sorted(a.coverage.unsupported_types),
            "warnings": a.warnings,
        }
        for a in analyses
    ]

    logger.info(
        "Analysis complete: %d workflows, %d total nodes, %.1f%% avg coverage",
        total,
        total_nodes,
        avg_coverage,
    )

    return {
        "total_workflows": total,
        "total_nodes": total_nodes,
        "avg_coverage": round(avg_coverage, 1),
        "avg_complexity": round(avg_complexity, 1),
        "workflows": workflows,
        "tool_frequency": dict(tool_counter.most_common()),
        "unsupported_tools": sorted(unsupported),
    }
