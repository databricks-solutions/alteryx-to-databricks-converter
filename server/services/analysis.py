"""Analysis service — wraps BatchAnalyzer."""

from __future__ import annotations

import logging
import tempfile
from collections import Counter
from pathlib import Path

from a2d.analyzer.batch import BatchAnalyzer
from a2d.analyzer.coverage import estate_coverage_percentage
from server.utils.package import analyze_each, macro_files, materialize_uploads, upload_name_for, write_macro_library

logger = logging.getLogger("a2d.server.services.analysis")


def analyze_files(files: list[tuple[str, bytes]]) -> dict:
    """Analyze uploaded .yxmd files and return analysis dict."""
    skipped: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        # .yxzp packages are unzipped to their primary workflow; other files pass through.
        paths = materialize_uploads(files, Path(tmpdir), skipped=skipped)

        # Expand macros so a .yxzp's co-located .yxmc, or a macro uploaded as its
        # own file, is inlined rather than shown as an unsupported Unknown.
        # One unreadable workflow is skipped and named, not fatal to the estate.
        analyzer = BatchAnalyzer(
            expand_macros=True, macro_search_paths=write_macro_library(macro_files(files), Path(tmpdir))
        )
        analyses = analyze_each(analyzer, paths, Path(tmpdir), files, skipped)
        sources = [upload_name_for(a.file_path, Path(tmpdir), files) for a in analyses]

    total = len(analyses)
    if total == 0:
        return {
            "total_workflows": 0,
            "total_nodes": 0,
            "avg_coverage": 0.0,
            "unresolved_macros": [],
            "avg_complexity": 0.0,
            "workflows": [],
            "tool_frequency": {},
            "unsupported_tools": [],
            "skipped_files": skipped,
        }

    # Same definition as each workflow's figure and as Convert's: supported tools
    # over all tools, across the estate.
    avg_coverage = estate_coverage_percentage([a.coverage for a in analyses])
    avg_complexity = sum(a.complexity.total_score for a in analyses) / total
    total_nodes = sum(a.coverage.total_nodes for a in analyses)  # tools, not canvas comments

    tool_counter: Counter = Counter()
    unsupported: set[str] = set()
    macros: dict[str, str] = {}
    for a in analyses:
        for tool_type, count in a.coverage.per_tool_counts.items():
            tool_counter[tool_type] += count
        unsupported.update(a.coverage.unsupported_types)
        for name, reason in a.coverage.unresolved_macros.items():
            macros.setdefault(name, reason)

    workflows = [
        {
            "file_name": Path(a.file_path).name,
            # The name as uploaded (a .yxzp's own name, not its primary workflow's),
            # so a result maps back to the file — or project workflow — it came from.
            "source_file_name": source,
            "workflow_name": a.workflow_name,
            "node_count": a.node_count,
            "connection_count": a.connection_count,
            "coverage_percentage": a.coverage.coverage_percentage,
            "type_coverage_percentage": a.coverage.type_coverage_percentage,
            "tool_count": a.coverage.total_nodes,
            "supported_tool_count": a.coverage.supported_nodes,
            "complexity_score": a.complexity.total_score,
            "complexity_level": a.complexity.level,
            "migration_priority": a.migration_priority,
            "estimated_effort": a.estimated_effort,
            "tool_types": sorted(a.tool_types_used),
            "unsupported_types": sorted(a.coverage.unsupported_types),
            "unresolved_macros": [{"name": n, "reason": r} for n, r in a.coverage.unresolved_macros.items()],
            "warnings": a.warnings,
        }
        for a, source in zip(analyses, sources, strict=True)
    ]

    logger.info(
        "Analysis complete: %d workflows, %d total nodes, %.1f%% coverage",
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
        # Macro calls that weren't expanded, named (not lumped in as a "Macro" tool type).
        "unresolved_macros": [{"name": n, "reason": r} for n, r in sorted(macros.items())],
        # Uploaded names that couldn't be read or analyzed, so totals aren't
        # mistaken for the whole estate.
        "skipped_files": skipped,
    }
