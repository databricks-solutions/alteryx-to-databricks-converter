"""Rendering for portfolio reports: rich console, HTML and JSON."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from a2d.__about__ import __version__
from a2d.portfolio.models import MigrationPlan, PortfolioReport


def print_portfolio_summary(report: PortfolioReport, console: Console) -> None:
    """Print a human-readable portfolio summary to the console."""
    console.print()
    console.rule("[bold]Portfolio analysis[/bold]")
    console.print(
        f"[bold]{report.workflow_count}[/bold] workflows · "
        f"[bold]{len(report.dependencies)}[/bold] cross-workflow dependencies · "
        f"[bold]{len(report.shared_macros)}[/bold] shared macros · "
        f"[bold]{len(report.duplicate_subflows)}[/bold] duplicate sub-flows"
    )

    _print_dependencies(report, console)
    _print_shared_macros(report, console)
    _print_duplicate_subflows(report, console)
    _print_plan(report.plan, console)

    if report.isolated_workflows:
        console.print(
            f"\n[dim]{len(report.isolated_workflows)} standalone workflow(s) with no shared "
            f"assets: {', '.join(report.isolated_workflows)}[/dim]"
        )


def _print_dependencies(report: PortfolioReport, console: Console) -> None:
    if not report.dependencies:
        return
    table = Table(title="Cross-workflow data dependencies")
    table.add_column("Producer", style="cyan")
    table.add_column("Consumer", style="green")
    table.add_column("Shared artifact", style="dim")
    for dep in report.dependencies:
        table.add_row(dep.producer, dep.consumer, dep.artifact)
    console.print(table)


def _print_shared_macros(report: PortfolioReport, console: Console) -> None:
    if not report.shared_macros:
        return
    table = Table(title="Shared macros")
    table.add_column("Macro", style="cyan")
    table.add_column("Used by", justify="right")
    table.add_column("Workflows", style="dim")
    for macro in report.shared_macros:
        table.add_row(macro.macro_path, str(macro.usage_count), ", ".join(macro.used_by))
    console.print(table)


def _print_duplicate_subflows(report: PortfolioReport, console: Console) -> None:
    if not report.duplicate_subflows:
        return
    table = Table(title="Duplicate sub-flows (migrate once, reuse)")
    table.add_column("Sub-flow (tools)", style="cyan")
    table.add_column("Copies", justify="right")
    table.add_column("Found in", style="dim")
    for dup in report.duplicate_subflows:
        table.add_row(dup.description, str(dup.occurrence_count), ", ".join(dup.found_in))
    console.print(table)


def _print_plan(plan: MigrationPlan, console: Console) -> None:
    if not plan.waves:
        return
    table = Table(title="Migration-wave plan (value × readiness ÷ effort)")
    table.add_column("Wave", justify="right")
    table.add_column("Workflow", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("Coverage", justify="right")
    table.add_column("Complexity", justify="right")
    table.add_column("Effort")
    table.add_column("Depends on", style="dim")
    for wave in plan.waves:
        for entry in wave.workflows:
            table.add_row(
                str(wave.wave),
                entry.workflow_name,
                f"{entry.score:.1f}",
                f"{entry.coverage_pct:.0f}%",
                f"{entry.complexity_score:.0f}",
                entry.estimated_effort,
                ", ".join(entry.depends_on) or "-",
            )
    console.print(table)
    console.print(
        f"[dim]Estimated total effort: ~{plan.total_effort_days:.0f} person-days "
        f"across {len(plan.waves)} wave(s).[/dim]"
    )


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def to_dict(report: PortfolioReport) -> dict:
    """Serialize a portfolio report to a JSON-ready dict.

    Shared by the CLI (``a2d portfolio --json``) and ``POST /api/portfolio`` so the
    two cannot drift into describing the same estate differently.
    """
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool_version": __version__,
        "summary": {
            "workflow_count": report.workflow_count,
            "dependency_count": len(report.dependencies),
            "shared_macro_count": len(report.shared_macros),
            "duplicate_subflow_count": len(report.duplicate_subflows),
            "isolated_workflow_count": len(report.isolated_workflows),
            "estimated_effort_days": round(report.plan.total_effort_days, 1),
            "wave_count": len(report.plan.waves),
        },
        "dependencies": [
            {"producer": d.producer, "consumer": d.consumer, "artifact": d.artifact} for d in report.dependencies
        ],
        "shared_macros": [
            {"macro_path": m.macro_path, "usage_count": m.usage_count, "used_by": m.used_by}
            for m in report.shared_macros
        ],
        "duplicate_subflows": [
            {
                "fingerprint": d.fingerprint,
                "description": d.description,
                "occurrence_count": d.occurrence_count,
                "found_in": d.found_in,
            }
            for d in report.duplicate_subflows
        ],
        "isolated_workflows": report.isolated_workflows,
        "migration_plan": {
            "waves": [
                {
                    "wave": w.wave,
                    "estimated_effort_days": round(w.total_effort_days, 1),
                    "workflows": [
                        {
                            "workflow_name": e.workflow_name,
                            "file_path": e.file_path,
                            "node_count": e.node_count,
                            "coverage_pct": e.coverage_pct,
                            "complexity_score": e.complexity_score,
                            "migration_priority": e.migration_priority,
                            "estimated_effort": e.estimated_effort,
                            "value": e.value,
                            "readiness": e.readiness,
                            "effort": e.effort,
                            "score": e.score,
                            "depends_on": e.depends_on,
                        }
                        for e in w.workflows
                    ],
                }
                for w in report.plan.waves
            ],
        },
    }


def generate_json(report: PortfolioReport, output_path: Path) -> None:
    """Write the portfolio report as JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(to_dict(report), indent=2) + "\n")


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


def generate_html(report: PortfolioReport, output_path: Path) -> None:
    """Write the portfolio report as a self-contained HTML page."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_build_html(report))


def _esc(text: str) -> str:
    """Minimal HTML escaping for interpolated values."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _build_html(report: PortfolioReport) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    dep_rows = (
        "".join(
            f"<tr><td>{_esc(d.producer)}</td><td>{_esc(d.consumer)}</td><td>{_esc(d.artifact)}</td></tr>"
            for d in report.dependencies
        )
        or '<tr><td colspan="3">No cross-workflow dependencies detected.</td></tr>'
    )

    macro_rows = (
        "".join(
            f"<tr><td>{_esc(m.macro_path)}</td><td>{m.usage_count}</td><td>{_esc(', '.join(m.used_by))}</td></tr>"
            for m in report.shared_macros
        )
        or '<tr><td colspan="3">No shared macros detected.</td></tr>'
    )

    dup_rows = (
        "".join(
            f"<tr><td>{_esc(d.description)}</td><td>{d.occurrence_count}</td><td>{_esc(', '.join(d.found_in))}</td></tr>"
            for d in report.duplicate_subflows
        )
        or '<tr><td colspan="3">No duplicate sub-flows detected.</td></tr>'
    )

    wave_rows = ""
    for wave in report.plan.waves:
        for entry in wave.workflows:
            effort_class = {"High": "badge-low", "Medium": "badge-medium", "Low": "badge-high"}.get(
                entry.estimated_effort, "badge-medium"
            )
            wave_rows += f"""
            <tr>
                <td>{wave.wave}</td>
                <td>{_esc(entry.workflow_name)}</td>
                <td>{entry.score:.1f}</td>
                <td>{entry.coverage_pct:.0f}%</td>
                <td>{entry.complexity_score:.0f}</td>
                <td><span class="badge {effort_class}">{entry.estimated_effort}</span></td>
                <td>{_esc(", ".join(entry.depends_on) or "-")}</td>
            </tr>"""
    if not wave_rows:
        wave_rows = '<tr><td colspan="7">No workflows to plan.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>a2d Portfolio Migration Report</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f4f6f9; color: #333; line-height: 1.6; padding: 2rem; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        header {{ background: linear-gradient(135deg, #1b3a57 0%, #2d6a9f 100%); color: white;
            padding: 2rem; border-radius: 8px; margin-bottom: 2rem; }}
        header h1 {{ font-size: 1.8rem; margin-bottom: 0.5rem; }}
        header p {{ opacity: 0.85; font-size: 0.9rem; }}
        .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem; margin-bottom: 2rem; }}
        .card {{ background: white; border-radius: 8px; padding: 1.5rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.08); }}
        .card h3 {{ font-size: 0.85rem; text-transform: uppercase; color: #888; margin-bottom: 0.5rem; }}
        .card .value {{ font-size: 2rem; font-weight: 700; color: #1b3a57; }}
        section {{ background: white; border-radius: 8px; padding: 1.5rem; margin-bottom: 2rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.08); }}
        section h2 {{ font-size: 1.3rem; color: #1b3a57; margin-bottom: 1rem;
            border-bottom: 2px solid #e8ecf1; padding-bottom: 0.5rem; }}
        table {{ border-collapse: collapse; width: 100%; font-size: 0.9rem; }}
        th {{ background: #f8f9fb; text-align: left; padding: 0.75rem;
            border-bottom: 2px solid #dee2e6; font-weight: 600; }}
        td {{ padding: 0.75rem; border-bottom: 1px solid #eee; }}
        tr:hover {{ background: #f8f9fb; }}
        .badge {{ display: inline-block; padding: 0.25em 0.6em; border-radius: 4px;
            font-size: 0.8rem; font-weight: 600; color: white; }}
        .badge-high {{ background-color: #28a745; }}
        .badge-medium {{ background-color: #ffc107; color: #333; }}
        .badge-low {{ background-color: #dc3545; }}
        footer {{ text-align: center; color: #999; font-size: 0.8rem; margin-top: 2rem; }}
    </style>
</head>
<body>
<div class="container">
    <header>
        <h1>Alteryx-to-Databricks Portfolio Migration Report</h1>
        <p>Generated by a2d v{__version__} on {generated_at}</p>
    </header>

    <div class="cards">
        <div class="card"><h3>Workflows</h3><div class="value">{report.workflow_count}</div></div>
        <div class="card"><h3>Dependencies</h3><div class="value">{len(report.dependencies)}</div></div>
        <div class="card"><h3>Shared Macros</h3><div class="value">{len(report.shared_macros)}</div></div>
        <div class="card"><h3>Duplicate Sub-flows</h3><div class="value">{len(report.duplicate_subflows)}</div></div>
        <div class="card"><h3>Est. Effort</h3><div class="value">{report.plan.total_effort_days:.0f}d</div></div>
    </div>

    <section>
        <h2>Migration-Wave Plan</h2>
        <p style="margin-bottom:1rem;color:#666;font-size:0.85rem">
            Ranked by value × readiness ÷ effort, sequenced so each workflow migrates no earlier
            than the workflows it depends on.</p>
        <table>
            <thead><tr><th>Wave</th><th>Workflow</th><th>Score</th><th>Coverage</th>
                <th>Complexity</th><th>Effort</th><th>Depends on</th></tr></thead>
            <tbody>{wave_rows}</tbody>
        </table>
    </section>

    <section>
        <h2>Cross-Workflow Data Dependencies</h2>
        <table>
            <thead><tr><th>Producer</th><th>Consumer</th><th>Shared artifact</th></tr></thead>
            <tbody>{dep_rows}</tbody>
        </table>
    </section>

    <section>
        <h2>Shared Macros</h2>
        <table>
            <thead><tr><th>Macro</th><th>Used by</th><th>Workflows</th></tr></thead>
            <tbody>{macro_rows}</tbody>
        </table>
    </section>

    <section>
        <h2>Duplicate Sub-flows</h2>
        <table>
            <thead><tr><th>Sub-flow (tools)</th><th>Copies</th><th>Found in</th></tr></thead>
            <tbody>{dup_rows}</tbody>
        </table>
    </section>

    <footer><p>a2d v{__version__} &mdash; Alteryx to Databricks Migration Accelerator</p></footer>
</div>
</body>
</html>
"""
