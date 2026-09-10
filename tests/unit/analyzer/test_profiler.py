"""Tests for the migration profiler (a2d.analyzer.profiler)."""

from __future__ import annotations

import json

import pytest

from a2d.analyzer.complexity import ComplexityScore
from a2d.analyzer.coverage import CoverageReport
from a2d.analyzer.profiler import (
    HIGH,
    LOW,
    MEDIUM,
    VERY_HIGH,
    ProfilerConfig,
    build_estate_profile,
    classify_tool,
    to_csv_rows,
)
from a2d.analyzer.readiness import WorkflowAnalysis


def _analysis(
    name: str,
    *,
    per_tool: dict[str, int],
    unsupported: set[str],
    level: str = "Low",
    score: float = 10.0,
    node_count: int | None = None,
    connections: int = 0,
    expressions: int = 0,
    depth: int = 1,
    macros: bool = False,
) -> WorkflowAnalysis:
    total = node_count if node_count is not None else sum(per_tool.values())
    supported = set(per_tool) - unsupported
    cov = CoverageReport(
        total_nodes=total,
        unique_tool_types=set(per_tool),
        supported_types=supported,
        unsupported_types=set(unsupported),
        coverage_percentage=round(len(supported) / max(len(per_tool), 1) * 100, 1),
        per_tool_counts=dict(per_tool),
    )
    cx = ComplexityScore(
        total_score=score,
        level=level,
        node_count=total,
        edge_count=connections,
        unique_tool_types=len(per_tool),
        unsupported_count=sum(per_tool[t] for t in unsupported if t in per_tool),
        expression_count=expressions,
        max_dag_depth=depth,
        has_macro_refs=macros,
    )
    return WorkflowAnalysis(
        file_path=f"/tmp/{name}.yxmd",
        workflow_name=name,
        complexity=cx,
        coverage=cov,
        node_count=total,
        connection_count=connections,
        tool_types_used=set(per_tool),
    )


class TestClassifyTool:
    def test_unsupported_always_very_high(self):
        # Even a normally-Low tool is Very High when it has no converter.
        assert classify_tool("Select", is_unsupported=True) == VERY_HIGH

    def test_override_wins_over_category(self):
        # Formula is in the "preparation" (Low) category but overridden to Medium.
        assert classify_tool("Formula", is_unsupported=False) == MEDIUM

    def test_category_default(self):
        assert classify_tool("Select", is_unsupported=False) == LOW
        assert classify_tool("Buffer", is_unsupported=False) == HIGH  # spatial
        assert classify_tool("Summarize", is_unsupported=False) == MEDIUM  # transform

    def test_custom_code_very_high(self):
        assert classify_tool("PythonTool", is_unsupported=False) == VERY_HIGH

    def test_unknown_tool_falls_back(self):
        assert classify_tool("SomeMysteryTool", is_unsupported=False) == MEDIUM

    def test_config_override_changes_tier(self):
        cfg = ProfilerConfig.default()
        cfg.tool_overrides["Filter"] = HIGH
        assert classify_tool("Filter", is_unsupported=False, config=cfg) == HIGH


class TestProfilerConfigFromFile:
    def test_yaml_merge(self, tmp_path):
        p = tmp_path / "cfg.yaml"
        p.write_text("tool_overrides:\n  Filter: High\nshow_hours: true\n")
        cfg = ProfilerConfig.from_file(p)
        assert cfg.tool_overrides["Filter"] == HIGH
        assert cfg.show_hours is True
        # Untouched defaults survive the merge.
        assert cfg.tool_overrides["PythonTool"] == VERY_HIGH

    def test_json_merge(self, tmp_path):
        p = tmp_path / "cfg.json"
        p.write_text(json.dumps({"category_tiers": {"io": "Medium"}, "hour_anchors": {"Low": 3}}))
        cfg = ProfilerConfig.from_file(p)
        assert cfg.category_tiers["io"] == MEDIUM
        assert cfg.hour_anchors["Low"] == 3.0

    def test_invalid_tier_rejected(self, tmp_path):
        p = tmp_path / "cfg.yaml"
        p.write_text("tool_overrides:\n  Filter: Impossible\n")
        with pytest.raises(ValueError, match="invalid tier"):
            ProfilerConfig.from_file(p)


class TestBuildEstateProfile:
    def _estate(self):
        return [
            _analysis(
                "wf1",
                per_tool={"Input": 1, "Formula": 2, "Buffer": 1, "Output": 1},
                unsupported=set(),
                level="Medium",
                score=40.0,
                connections=4,
                expressions=2,
                depth=3,
            ),
            _analysis(
                "wf2",
                per_tool={"Input": 1, "PythonTool": 1},
                unsupported={"PythonTool"},
                level="Low",
                score=12.0,
                connections=1,
                depth=2,
                macros=True,
            ),
        ]

    def test_totals_and_distribution(self):
        p = build_estate_profile(self._estate())
        assert p.total_workflows == 2
        assert p.total_tools == 7  # wf1: 5 nodes, wf2: 2 nodes
        assert p.total_connections == 5
        assert p.total_expressions == 2
        assert p.total_data_sources == 2  # two Input tools
        assert p.workflows_with_macros == 1
        assert p.difficulty_distribution == {"Low": 1, "Medium": 1, "High": 0, "Very High": 0}

    def test_tool_tier_counts(self):
        p = build_estate_profile(self._estate())
        # Input(2)+Output(1)=3 Low; Formula(2)=2 Medium; Buffer(1)=1 High;
        # PythonTool(1) unsupported => Very High.
        assert p.tool_tier_counts[LOW] == 3
        assert p.tool_tier_counts[MEDIUM] == 2
        assert p.tool_tier_counts[HIGH] == 1
        assert p.tool_tier_counts[VERY_HIGH] == 1
        assert "PythonTool" in p.tool_tier_types[VERY_HIGH]

    def test_size_distribution(self):
        p = build_estate_profile(self._estate())
        assert p.max_tools == 5
        assert "wf1" in p.max_tools_workflow
        assert p.workflows[0].workflow_name == "wf1"  # sorted by score desc

    def test_hours_off_by_default(self):
        p = build_estate_profile(self._estate())
        assert p.total_hours is None
        assert all(w.estimated_hours is None for w in p.workflows)

    def test_hours_when_enabled(self):
        cfg = ProfilerConfig.default()
        cfg.show_hours = True
        p = build_estate_profile(self._estate(), cfg)
        # Medium(8) + Low(2) = 10 by default anchors.
        assert p.total_hours == 10.0

    def test_csv_rows(self):
        p = build_estate_profile(self._estate())
        rows = to_csv_rows(p)
        assert rows[0][0] == "workflow_name"
        assert len(rows) == 3  # header + 2 workflows
