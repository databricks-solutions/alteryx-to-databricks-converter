"""Report generation for migration readiness analysis."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from a2d.__about__ import __version__
from a2d.analyzer.readiness import WorkflowAnalysis
from a2d.parser.schema import TOOL_METADATA


class ReportGenerator:
    """Generate HTML and JSON migration readiness reports."""

    def generate_html(self, analyses: list[WorkflowAnalysis], output_path: Path) -> None:
        """Generate an HTML migration report."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Compute aggregate stats
        total_workflows = len(analyses)
        if total_workflows == 0:
            avg_coverage = 0.0
            avg_complexity = 0.0
        else:
            avg_coverage = sum(a.coverage.coverage_percentage for a in analyses) / total_workflows
            avg_complexity = sum(a.complexity.total_score for a in analyses) / total_workflows

        total_nodes = sum(a.node_count for a in analyses)

        # Tool frequency across all workflows
        tool_counter: Counter = Counter()
        unsupported_tools: set[str] = set()
        for a in analyses:
            for tool_type, count in a.coverage.per_tool_counts.items():
                tool_counter[tool_type] += count
            unsupported_tools.update(a.coverage.unsupported_types)

        # Priority distribution
        priority_counts = Counter(a.migration_priority for a in analyses)
        effort_counts = Counter(a.estimated_effort for a in analyses)

        # Build HTML
        html = self._build_html(
            analyses=analyses,
            total_workflows=total_workflows,
            avg_coverage=avg_coverage,
            avg_complexity=avg_complexity,
            total_nodes=total_nodes,
            tool_counter=tool_counter,
            unsupported_tools=unsupported_tools,
            priority_counts=priority_counts,
            effort_counts=effort_counts,
        )

        output_path.write_text(html)

    def generate_json(self, analyses: list[WorkflowAnalysis], output_path: Path) -> None:
        """Generate a JSON migration report."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        total_workflows = len(analyses)
        if total_workflows == 0:
            avg_coverage = 0.0
            avg_complexity = 0.0
        else:
            avg_coverage = sum(a.coverage.coverage_percentage for a in analyses) / total_workflows
            avg_complexity = sum(a.complexity.total_score for a in analyses) / total_workflows

        tool_counter: Counter = Counter()
        unsupported_tools: set[str] = set()
        for a in analyses:
            for tool_type, count in a.coverage.per_tool_counts.items():
                tool_counter[tool_type] += count
            unsupported_tools.update(a.coverage.unsupported_types)

        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "tool_version": __version__,
            "summary": {
                "total_workflows": total_workflows,
                "total_nodes": sum(a.node_count for a in analyses),
                "average_coverage_pct": round(avg_coverage, 1),
                "average_complexity": round(avg_complexity, 1),
            },
            "workflows": [
                {
                    "file_path": a.file_path,
                    "workflow_name": a.workflow_name,
                    "node_count": a.node_count,
                    "connection_count": a.connection_count,
                    "coverage_pct": a.coverage.coverage_percentage,
                    "complexity_score": a.complexity.total_score,
                    "complexity_level": a.complexity.level,
                    "migration_priority": a.migration_priority,
                    "estimated_effort": a.estimated_effort,
                    "tool_types": sorted(a.tool_types_used),
                    "unsupported_types": sorted(a.coverage.unsupported_types),
                    "warnings": a.warnings,
                }
                for a in analyses
            ],
            "tool_frequency": dict(tool_counter.most_common()),
            "unsupported_tools": sorted(unsupported_tools),
        }

        output_path.write_text(json.dumps(report, indent=2) + "\n")

    def _build_html(
        self,
        analyses: list[WorkflowAnalysis],
        total_workflows: int,
        avg_coverage: float,
        avg_complexity: float,
        total_nodes: int,
        tool_counter: Counter,
        unsupported_tools: set[str],
        priority_counts: Counter,
        effort_counts: Counter,
    ) -> str:
        """Build the full HTML report string."""
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        # Build workflow rows
        workflow_rows = ""
        for a in analyses:
            priority_class = {
                "High": "badge-high",
                "Medium": "badge-medium",
                "Low": "badge-low",
            }.get(a.migration_priority, "badge-medium")

            effort_class = {
                "High": "badge-high",
                "Medium": "badge-medium",
                "Low": "badge-low",
            }.get(a.estimated_effort, "badge-medium")

            coverage_class = ""
            if a.coverage.coverage_percentage >= 80:
                coverage_class = "text-success"
            elif a.coverage.coverage_percentage >= 50:
                coverage_class = "text-warning"
            else:
                coverage_class = "text-danger"

            workflow_rows += f"""
            <tr>
                <td>{a.workflow_name}</td>
                <td>{a.node_count}</td>
                <td>{a.connection_count}</td>
                <td class="{coverage_class}">{a.coverage.coverage_percentage:.1f}%</td>
                <td>{a.complexity.total_score:.1f} ({a.complexity.level})</td>
                <td><span class="badge {priority_class}">{a.migration_priority}</span></td>
                <td><span class="badge {effort_class}">{a.estimated_effort}</span></td>
            </tr>"""

        # Build tool frequency rows
        tool_rows = ""
        max_count = max(tool_counter.values()) if tool_counter else 1
        _method_colors = {
            "deterministic": "#28a745",
            "expression-engine": "#007bff",
            "template": "#ffc107",
            "mapping": "#fd7e14",
        }
        for tool_type, count in tool_counter.most_common(20):
            bar_width = int((count / max_count) * 100)
            is_unsupported = tool_type in unsupported_tools
            status_badge = (
                '<span class="badge badge-low">Unsupported</span>'
                if is_unsupported
                else '<span class="badge badge-high">Supported</span>'
            )
            meta = TOOL_METADATA.get(tool_type)
            method = meta.conversion_method if meta else "-"
            method_color = _method_colors.get(method, "#999")
            method_badge = f'<span class="badge" style="background:{method_color};color:#fff">{method}</span>'
            tool_rows += f"""
            <tr>
                <td>{tool_type}</td>
                <td>{count}</td>
                <td>
                    <div class="bar-container">
                        <div class="bar" style="width: {bar_width}%"></div>
                    </div>
                </td>
                <td>{status_badge}</td>
                <td>{method_badge}</td>
            </tr>"""

        # Build unsupported tools list
        unsupported_list = ""
        if unsupported_tools:
            items = "".join(f"<li>{t}</li>" for t in sorted(unsupported_tools))
            unsupported_list = f"<ul>{items}</ul>"
        else:
            unsupported_list = "<p>All tools are supported.</p>"

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>a2d Migration Readiness Report</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, sans-serif;
            background: #f4f6f9;
            color: #333;
            line-height: 1.6;
            padding: 2rem;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        header {{
            background: linear-gradient(135deg, #1b3a57 0%, #2d6a9f 100%);
            color: white;
            padding: 2rem;
            border-radius: 8px;
            margin-bottom: 2rem;
        }}
        header h1 {{ font-size: 1.8rem; margin-bottom: 0.5rem; }}
        header p {{ opacity: 0.85; font-size: 0.9rem; }}
        .cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}
        .card {{
            background: white;
            border-radius: 8px;
            padding: 1.5rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.08);
        }}
        .card h3 {{ font-size: 0.85rem; text-transform: uppercase; color: #888; margin-bottom: 0.5rem; }}
        .card .value {{ font-size: 2rem; font-weight: 700; color: #1b3a57; }}
        .card .sub {{ font-size: 0.8rem; color: #999; }}
        section {{
            background: white;
            border-radius: 8px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.08);
        }}
        section h2 {{
            font-size: 1.3rem; color: #1b3a57; margin-bottom: 1rem;
            border-bottom: 2px solid #e8ecf1; padding-bottom: 0.5rem;
        }}
        table {{ border-collapse: collapse; width: 100%; font-size: 0.9rem; }}
        th {{
            background: #f8f9fb; text-align: left; padding: 0.75rem;
            border-bottom: 2px solid #dee2e6; font-weight: 600;
        }}
        td {{ padding: 0.75rem; border-bottom: 1px solid #eee; }}
        tr:hover {{ background: #f8f9fb; }}
        .badge {{
            display: inline-block;
            padding: 0.25em 0.6em;
            border-radius: 4px;
            font-size: 0.8rem;
            font-weight: 600;
            color: white;
        }}
        .badge-high {{ background-color: #28a745; }}
        .badge-medium {{ background-color: #ffc107; color: #333; }}
        .badge-low {{ background-color: #dc3545; }}
        .text-success {{ color: #28a745; font-weight: 600; }}
        .text-warning {{ color: #e6a700; font-weight: 600; }}
        .text-danger {{ color: #dc3545; font-weight: 600; }}
        .bar-container {{ background: #eee; border-radius: 4px; height: 18px; width: 100%; }}
        .bar {{ background: linear-gradient(90deg, #2d6a9f, #4a90d9); height: 100%; border-radius: 4px; min-width: 4px; }}
        footer {{ text-align: center; color: #999; font-size: 0.8rem; margin-top: 2rem; }}
    </style>
</head>
<body>
<div class="container">
    <header>
        <h1>Alteryx-to-Databricks Migration Readiness Report</h1>
        <p>Generated by a2d v{__version__} on {generated_at}</p>
    </header>

    <div class="cards">
        <div class="card">
            <h3>Total Workflows</h3>
            <div class="value">{total_workflows}</div>
        </div>
        <div class="card">
            <h3>Total Nodes</h3>
            <div class="value">{total_nodes}</div>
        </div>
        <div class="card">
            <h3>Avg Coverage</h3>
            <div class="value">{avg_coverage:.1f}%</div>
            <div class="sub">of tool types supported</div>
        </div>
        <div class="card">
            <h3>Avg Complexity</h3>
            <div class="value">{avg_complexity:.1f}</div>
            <div class="sub">out of 100</div>
        </div>
    </div>

    <section>
        <h2>Per-Workflow Analysis</h2>
        <table>
            <thead>
                <tr>
                    <th>Workflow</th>
                    <th>Nodes</th>
                    <th>Connections</th>
                    <th>Coverage</th>
                    <th>Complexity</th>
                    <th>Priority</th>
                    <th>Effort</th>
                </tr>
            </thead>
            <tbody>
                {workflow_rows}
            </tbody>
        </table>
    </section>

    <section>
        <h2>Tool Frequency Analysis</h2>
        <table>
            <thead>
                <tr>
                    <th>Tool Type</th>
                    <th>Count</th>
                    <th>Frequency</th>
                    <th>Status</th>
                    <th>Method</th>
                </tr>
            </thead>
            <tbody>
                {tool_rows}
            </tbody>
        </table>
    </section>

    <section>
        <h2>Unsupported Tools</h2>
        {unsupported_list}
    </section>

    <footer>
        <p>a2d v{__version__} &mdash; Alteryx to Databricks Migration Accelerator</p>
    </footer>
</div>
</body>
</html>
"""
        return html
