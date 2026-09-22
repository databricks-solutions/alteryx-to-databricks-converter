"""Savings / ROI calculator — deterministic math over analysis facts + assumptions.

Grounds every dollar in what the converter actually found (workflow count,
per-workflow effort tier, coverage) and a set of editable cost assumptions. There
is no model call and no persisted state; the same inputs always yield the same
report.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from a2d.savings.model import (
    CostAssumptions,
    EstateFacts,
    SavingsLine,
    SavingsReport,
)

if TYPE_CHECKING:
    from a2d.analyzer.readiness import WorkflowAnalysis


def estate_facts(analyses: list[WorkflowAnalysis], hour_anchors: dict[str, float]) -> EstateFacts:
    """Roll a list of per-workflow analyses into estate-level effort facts.

    ``total_manual_hours`` sums each workflow's effort-tier anchor hours — the same
    Low/Med/High/Very-High → hours model the profiler uses. Mean coverage is
    node-instance-weighted so a 2-node and a 200-node workflow don't count equally.
    """
    workflows_by_level: dict[str, int] = {}
    hours_by_level: dict[str, float] = {}
    total_hours = 0.0
    weighted_cov = 0.0
    total_nodes = 0

    for wf in analyses:
        level = wf.complexity.level
        anchor = float(hour_anchors.get(level, 0.0))
        workflows_by_level[level] = workflows_by_level.get(level, 0) + 1
        hours_by_level[level] = hours_by_level.get(level, 0.0) + anchor
        total_hours += anchor

        nodes = max(wf.node_count, 0)
        # Prefer instance-weighted coverage; fall back to type coverage.
        cov = getattr(wf.coverage, "instance_coverage_percentage", wf.coverage.coverage_percentage)
        weighted_cov += cov * nodes
        total_nodes += nodes

    mean_cov = (weighted_cov / total_nodes) if total_nodes else 100.0

    return EstateFacts(
        workflow_count=len(analyses),
        total_manual_hours=total_hours,
        hours_by_level=hours_by_level,
        workflows_by_level=workflows_by_level,
        mean_coverage_pct=mean_cov,
    )


class SavingsCalculator:
    """Compute a :class:`SavingsReport` from analyses + assumptions."""

    def compute(
        self,
        analyses: list[WorkflowAnalysis],
        assumptions: CostAssumptions | None = None,
    ) -> SavingsReport:
        a = assumptions or CostAssumptions.default()
        facts = estate_facts(analyses, a.hour_anchors)

        # --- Automation factor: explicit override, else derived from coverage ---
        if a.automation_factor is not None:
            automation = max(0.0, min(1.0, a.automation_factor))
        else:
            automation = max(0.0, min(1.0, facts.mean_coverage_pct / 100.0))

        # --- One-time developer economics ---
        dev_hours_avoided = facts.total_manual_hours * automation
        dev_hours_remaining = facts.total_manual_hours - dev_hours_avoided
        review_hours = a.review_hours_per_workflow * facts.workflow_count
        dev_time_saved = dev_hours_avoided * a.developer_hourly_rate
        migration_investment = (dev_hours_remaining + review_hours) * a.developer_hourly_rate

        # --- Annual recurring lines ---
        alteryx_license_savings = (
            a.designer_seats * a.designer_cost_per_seat_year + a.server_licenses * a.server_cost_per_license_year
        )
        maintenance_savings = a.annual_maintenance_savings
        databricks_run_cost = a.dbu_price * a.dbu_per_workflow_run * a.runs_per_month * 12.0 * facts.workflow_count
        net_annual = alteryx_license_savings + maintenance_savings - databricks_run_cost

        # --- Rollup over the horizon (one-time net + recurring * years) ---
        horizon = a.analysis_horizon_years
        cumulative_net = (dev_time_saved - migration_investment) + net_annual * horizon

        # Payback: credit the one-time dev-time saving against the investment first,
        # then recover any residual from the recurring net. None when it can't.
        residual = migration_investment - dev_time_saved
        if residual <= 0:
            payback_months: float | None = 0.0
        elif net_annual > 0:
            payback_months = residual / (net_annual / 12.0)
        else:
            payback_months = None

        # ROI over the horizon against the migration investment.
        if migration_investment > 0:
            total_gains = dev_time_saved + net_annual * horizon
            roi_pct: float | None = (total_gains - migration_investment) / migration_investment * 100.0
        else:
            roi_pct = None

        lines = [
            SavingsLine(
                key="dev_time_saved",
                label="Developer rewrite time saved (automation)",
                amount=dev_time_saved,
                kind="one_time",
                direction="saving",
            ),
            SavingsLine(
                key="migration_investment",
                label="Migration investment (finish + review generated code)",
                amount=migration_investment,
                kind="one_time",
                direction="investment",
            ),
            SavingsLine(
                key="alteryx_license_savings",
                label="Alteryx licenses retired",
                amount=alteryx_license_savings,
                kind="annual",
                direction="saving",
            ),
            SavingsLine(
                key="maintenance_savings",
                label="Ongoing maintenance / opex reduced",
                amount=maintenance_savings,
                kind="annual",
                direction="saving",
            ),
            SavingsLine(
                key="databricks_run_cost",
                label="Databricks run cost (new)",
                amount=databricks_run_cost,
                kind="annual",
                direction="cost",
            ),
        ]

        return SavingsReport(
            currency=a.currency,
            estate=facts,
            assumptions=a,
            lines=lines,
            automation_factor_effective=automation,
            dev_hours_avoided=dev_hours_avoided,
            dev_time_saved=dev_time_saved,
            migration_investment=migration_investment,
            alteryx_license_savings=alteryx_license_savings,
            maintenance_savings=maintenance_savings,
            databricks_run_cost=databricks_run_cost,
            net_annual_savings=net_annual,
            cumulative_net=cumulative_net,
            payback_months=payback_months,
            roi_pct=roi_pct,
        )
