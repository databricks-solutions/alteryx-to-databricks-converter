"""Executive migration dashboard: estate-wide coverage / effort / risk rollups.

Consumes a :class:`~a2d.portfolio.models.PortfolioReport` and renders a single
self-contained HTML page aimed at a decision-maker: how big is the estate, how
much is ready today, where the risk concentrates, what it will cost, and where
reuse can cut that cost. Charts are inline SVG so the file prints/exports to PDF
with no external assets.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from a2d.__about__ import __version__
from a2d.analyzer.readiness import WorkflowAnalysis
from a2d.portfolio.models import PortfolioReport

# Risk tiers derived from coverage + complexity. These mirror the intent of the
# per-conversion deploy banner but work from analysis alone (no code-gen pass).
_READY_COVERAGE = 90.0
_REVIEW_COVERAGE = 70.0
_HIGH_COMPLEXITY = 75.0


@dataclass
class EstateRollup:
    """Aggregated estate-wide metrics for the executive view."""

    workflow_count: int
    total_nodes: int
    avg_coverage: float
    total_effort_days: float
    wave_count: int
    ready_count: int
    review_count: int
    high_risk_count: int
    complexity_bands: dict[str, int]  # Low/Medium/High/Very High -> count
    coverage_bands: dict[str, int]  # band label -> count
    top_unsupported: list[tuple[str, int]]  # (tool, workflow-count) desc
    reuse_macro_count: int
    reuse_subflow_count: int
    reuse_savings_days: float


def risk_tier(analysis: WorkflowAnalysis) -> str:
    """Classify a workflow into ready / needs_review / high_risk."""
    cov = analysis.coverage.coverage_percentage
    complexity = analysis.complexity.total_score
    if cov < _REVIEW_COVERAGE or complexity >= _HIGH_COMPLEXITY:
        return "high_risk"
    if cov >= _READY_COVERAGE and complexity < 50:
        return "ready"
    return "needs_review"


def build_rollup(report: PortfolioReport) -> EstateRollup:
    """Aggregate a portfolio report into executive-level estate metrics."""
    analyses = report.analyses
    n = len(analyses)
    total_nodes = sum(a.node_count for a in analyses)
    avg_coverage = sum(a.coverage.coverage_percentage for a in analyses) / n if n else 0.0

    tiers = Counter(risk_tier(a) for a in analyses)
    complexity_bands = Counter(a.complexity.level for a in analyses)
    coverage_bands = Counter(_coverage_band(a.coverage.coverage_percentage) for a in analyses)

    # Which unsupported tools block the most workflows (breadth, not raw count).
    unsupported_breadth: Counter[str] = Counter()
    for a in analyses:
        for tool in a.coverage.unsupported_types:
            unsupported_breadth[tool] += 1

    # Reuse: each duplicate sub-flow past the first copy and each shared-macro
    # extra use is work that consolidation removes. Value it at ~1 day apiece as
    # a conservative planning proxy.
    dup_extra = sum(max(0, d.occurrence_count - 1) for d in report.duplicate_subflows)
    macro_extra = sum(max(0, m.usage_count - 1) for m in report.shared_macros)
    reuse_savings_days = float(dup_extra + macro_extra)

    return EstateRollup(
        workflow_count=n,
        total_nodes=total_nodes,
        avg_coverage=round(avg_coverage, 1),
        total_effort_days=round(report.plan.total_effort_days, 1),
        wave_count=len(report.plan.waves),
        ready_count=tiers.get("ready", 0),
        review_count=tiers.get("needs_review", 0),
        high_risk_count=tiers.get("high_risk", 0),
        complexity_bands=dict(complexity_bands),
        coverage_bands=dict(coverage_bands),
        top_unsupported=unsupported_breadth.most_common(10),
        reuse_macro_count=len(report.shared_macros),
        reuse_subflow_count=len(report.duplicate_subflows),
        reuse_savings_days=reuse_savings_days,
    )


def _coverage_band(pct: float) -> str:
    if pct >= 90:
        return "90-100%"
    if pct >= 70:
        return "70-89%"
    if pct >= 50:
        return "50-69%"
    return "<50%"


def generate_dashboard(report: PortfolioReport, output_path: Path) -> None:
    """Write the executive dashboard HTML."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_build_html(report, build_rollup(report)))


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

_COVERAGE_BAND_ORDER = ("90-100%", "70-89%", "50-69%", "<50%")
_COMPLEXITY_ORDER = ("Low", "Medium", "High", "Very High")


def _bar_chart(rows: list[tuple[str, int]], colors: dict[str, str] | None = None) -> str:
    """Render a horizontal bar chart as an HTML/CSS block (print-friendly)."""
    if not rows:
        return "<p>No data.</p>"
    max_val = max((v for _, v in rows), default=1) or 1
    out = ['<div class="chart">']
    for label, value in rows:
        pct = int(value / max_val * 100)
        color = (colors or {}).get(label, "#2d6a9f")
        out.append(
            f'<div class="chart-row"><span class="chart-label">{_esc(label)}</span>'
            f'<span class="chart-bar-wrap"><span class="chart-bar" style="width:{pct}%;background:{color}">'
            f'</span></span><span class="chart-value">{value}</span></div>'
        )
    out.append("</div>")
    return "".join(out)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _build_html(report: PortfolioReport, roll: EstateRollup) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    risk_chart = _bar_chart(
        [
            ("Ready", roll.ready_count),
            ("Needs review", roll.review_count),
            ("High risk", roll.high_risk_count),
        ],
        colors={"Ready": "#28a745", "Needs review": "#e6a700", "High risk": "#dc3545"},
    )

    complexity_chart = _bar_chart(
        [(band, roll.complexity_bands.get(band, 0)) for band in _COMPLEXITY_ORDER if roll.complexity_bands.get(band)],
        colors={"Low": "#28a745", "Medium": "#e6a700", "High": "#fd7e14", "Very High": "#dc3545"},
    )

    coverage_chart = _bar_chart(
        [(band, roll.coverage_bands.get(band, 0)) for band in _COVERAGE_BAND_ORDER if roll.coverage_bands.get(band)],
        colors={"90-100%": "#28a745", "70-89%": "#a3c644", "50-69%": "#e6a700", "<50%": "#dc3545"},
    )

    effort_chart = _bar_chart(
        [(f"Wave {w.wave}", round(w.total_effort_days)) for w in report.plan.waves],
    )

    unsupported_rows = (
        "".join(f"<tr><td>{_esc(tool)}</td><td>{count}</td></tr>" for tool, count in roll.top_unsupported)
        or '<tr><td colspan="2">No unsupported tools — the estate is fully covered.</td></tr>'
    )

    ready_pct = round(roll.ready_count / roll.workflow_count * 100) if roll.workflow_count else 0

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>a2d Executive Migration Dashboard</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f4f6f9; color: #2b2b2b; line-height: 1.55; padding: 2rem; }}
        .container {{ max-width: 1100px; margin: 0 auto; }}
        header {{ background: linear-gradient(135deg, #12263a 0%, #2d6a9f 100%); color: white;
            padding: 2rem; border-radius: 10px; margin-bottom: 1.5rem; }}
        header h1 {{ font-size: 1.7rem; margin-bottom: 0.35rem; }}
        header p {{ opacity: 0.85; font-size: 0.9rem; }}
        .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
            gap: 1rem; margin-bottom: 1.5rem; }}
        .kpi {{ background: white; border-radius: 10px; padding: 1.25rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.07); }}
        .kpi h3 {{ font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em;
            color: #8a94a2; margin-bottom: 0.4rem; }}
        .kpi .value {{ font-size: 1.9rem; font-weight: 700; color: #12263a; }}
        .kpi .sub {{ font-size: 0.75rem; color: #9aa3af; }}
        .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }}
        @media (max-width: 720px) {{ .grid2 {{ grid-template-columns: 1fr; }} }}
        section {{ background: white; border-radius: 10px; padding: 1.5rem; margin-bottom: 1.5rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.07); }}
        section h2 {{ font-size: 1.15rem; color: #12263a; margin-bottom: 1rem;
            border-bottom: 2px solid #eef1f5; padding-bottom: 0.5rem; }}
        .chart-row {{ display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.5rem; }}
        .chart-label {{ width: 110px; font-size: 0.82rem; color: #556; text-align: right; }}
        .chart-bar-wrap {{ flex: 1; background: #eef1f5; border-radius: 4px; height: 18px; }}
        .chart-bar {{ display: block; height: 100%; border-radius: 4px; min-width: 3px; }}
        .chart-value {{ width: 36px; font-size: 0.82rem; font-weight: 600; color: #333; }}
        table {{ border-collapse: collapse; width: 100%; font-size: 0.88rem; }}
        th {{ background: #f7f9fb; text-align: left; padding: 0.6rem; border-bottom: 2px solid #e2e8f0;
            font-weight: 600; }}
        td {{ padding: 0.6rem; border-bottom: 1px solid #eef1f5; }}
        .callout {{ background: #eef7ef; border-left: 4px solid #28a745; padding: 1rem 1.25rem;
            border-radius: 6px; font-size: 0.9rem; }}
        footer {{ text-align: center; color: #9aa3af; font-size: 0.78rem; margin-top: 1.5rem; }}
    </style>
</head>
<body>
<div class="container">
    <header>
        <h1>Alteryx-to-Databricks Executive Migration Dashboard</h1>
        <p>Estate-wide readiness, effort and risk &middot; generated by a2d v{__version__} on {generated_at}</p>
    </header>

    <div class="kpis">
        <div class="kpi"><h3>Workflows</h3><div class="value">{roll.workflow_count}</div>
            <div class="sub">{roll.total_nodes} tools total</div></div>
        <div class="kpi"><h3>Avg Coverage</h3><div class="value">{roll.avg_coverage:.0f}%</div>
            <div class="sub">of tool types auto-converted</div></div>
        <div class="kpi"><h3>Ready to Migrate</h3><div class="value">{roll.ready_count}</div>
            <div class="sub">{ready_pct}% of the estate</div></div>
        <div class="kpi"><h3>Est. Effort</h3><div class="value">{roll.total_effort_days:.0f}d</div>
            <div class="sub">across {roll.wave_count} wave(s)</div></div>
        <div class="kpi"><h3>Reuse Savings</h3><div class="value">~{roll.reuse_savings_days:.0f}d</div>
            <div class="sub">via shared macros / sub-flows</div></div>
    </div>

    <div class="grid2">
        <section>
            <h2>Migration Readiness</h2>
            {risk_chart}
        </section>
        <section>
            <h2>Coverage Distribution</h2>
            {coverage_chart}
        </section>
    </div>

    <div class="grid2">
        <section>
            <h2>Complexity Distribution</h2>
            {complexity_chart}
        </section>
        <section>
            <h2>Effort by Wave (person-days)</h2>
            {effort_chart}
        </section>
    </div>

    <section>
        <h2>Top Migration Blockers</h2>
        <p style="color:#667;font-size:0.85rem;margin-bottom:0.8rem">
            Unsupported tools ranked by how many workflows they appear in — the highest-leverage
            converters to build or manually address next.</p>
        <table>
            <thead><tr><th>Unsupported tool</th><th>Workflows affected</th></tr></thead>
            <tbody>{unsupported_rows}</tbody>
        </table>
    </section>

    <section>
        <h2>Consolidation Opportunities</h2>
        <div class="callout">
            <strong>{roll.reuse_macro_count}</strong> macro(s) and
            <strong>{roll.reuse_subflow_count}</strong> duplicated sub-flow(s) are shared across
            workflows. Migrating each once as a reusable Unity Catalog function / Designer component
            — rather than per copy — is estimated to save <strong>~{roll.reuse_savings_days:.0f}
            person-days</strong> and keep the logic consistent estate-wide.
        </div>
    </section>

    <footer><p>a2d v{__version__} &mdash; Alteryx to Databricks Migration Accelerator</p></footer>
</div>
</body>
</html>
"""
