"""Analysis service — wraps BatchAnalyzer."""

from __future__ import annotations

import logging
import tempfile
from collections import Counter
from pathlib import Path

from a2d.analyzer.batch import BatchAnalyzer
from server.utils.package import materialize_uploads

logger = logging.getLogger("a2d.server.services.analysis")


def _source_name(file_path: str | Path, base_dir: Path, files: list[tuple[str, bytes]]) -> str:
    """Map a materialized workflow path back to the uploaded file's name.

    ``materialize_uploads`` writes upload *i* under ``base_dir/upload_<i>/``
    (a package's primary workflow may sit deeper), so the first path component
    identifies the upload.
    """
    try:
        first = Path(file_path).resolve().relative_to(base_dir.resolve()).parts[0]
        index = int(first.removeprefix("upload_"))
        return files[index][0]
    except (ValueError, IndexError):
        return Path(file_path).name


def analyze_files(files: list[tuple[str, bytes]]) -> dict:
    """Analyze uploaded .yxmd files and return analysis dict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # .yxzp packages are unzipped to their primary workflow; other files pass through.
        paths = materialize_uploads(files, Path(tmpdir))

        # Expand macros so a .yxzp's co-located .yxmc is inlined rather than shown
        # as an unsupported Unknown; a no-op for bare uploads with no macro file.
        analyzer = BatchAnalyzer(expand_macros=True)
        analyses = analyzer.analyze_files(paths)
        sources = [_source_name(a.file_path, Path(tmpdir), files) for a in analyses]

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
            # The name as uploaded (a .yxzp's own name, not its primary workflow's),
            # so a result maps back to the file — or project workflow — it came from.
            "source_file_name": source,
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
        for a, source in zip(analyses, sources, strict=True)
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
