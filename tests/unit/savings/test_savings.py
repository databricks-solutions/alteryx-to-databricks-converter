"""Unit tests for the savings / ROI estimator (deterministic math)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from a2d.savings import CostAssumptions, SavingsCalculator, estate_facts


def _wf(level: str, coverage: float = 100.0, nodes: int = 10, macros: bool = False):
    """A minimal WorkflowAnalysis-shaped stub the calculator can read."""
    return SimpleNamespace(
        complexity=SimpleNamespace(level=level, has_macro_refs=macros, spatial_tool_count=0),
        coverage=SimpleNamespace(coverage_percentage=coverage, instance_coverage_percentage=coverage),
        node_count=nodes,
        tool_types_used={"Filter"},
    )


def test_estate_facts_sums_hours_by_tier():
    anchors = {"Low": 2.0, "Medium": 8.0, "High": 16.0, "Very High": 40.0}
    facts = estate_facts([_wf("Low"), _wf("Low"), _wf("High")], anchors)
    assert facts.workflow_count == 3
    assert facts.total_manual_hours == 2.0 + 2.0 + 16.0
    assert facts.workflows_by_level == {"Low": 2, "High": 1}
    assert facts.hours_by_level == {"Low": 4.0, "High": 16.0}


def test_mean_coverage_is_node_weighted():
    # 100-node @ 90% vs 10-node @ 50% → weighted toward the big one.
    facts = estate_facts(
        [_wf("Low", coverage=90.0, nodes=100), _wf("Low", coverage=50.0, nodes=10)],
        {"Low": 2.0},
    )
    assert facts.mean_coverage_pct == pytest.approx((90 * 100 + 50 * 10) / 110)


def test_compute_headline_with_explicit_automation():
    a = CostAssumptions.default()
    a.automation_factor = 0.5
    a.developer_hourly_rate = 100.0
    a.review_hours_per_workflow = 0.0
    a.hour_anchors = {"Medium": 10.0}
    # single 10h workflow, automation 0.5 → 5h avoided, 5h remaining
    rep = SavingsCalculator().compute([_wf("Medium")], a)
    assert rep.dev_hours_avoided == pytest.approx(5.0)
    assert rep.dev_time_saved == pytest.approx(500.0)
    assert rep.migration_investment == pytest.approx(500.0)  # 5h remaining + 0 review
    # license savings = seats*cost + servers*cost
    assert rep.alteryx_license_savings == pytest.approx(
        a.designer_seats * a.designer_cost_per_seat_year + a.server_licenses * a.server_cost_per_license_year
    )
    assert rep.net_annual_savings == pytest.approx(
        rep.alteryx_license_savings + rep.maintenance_savings - rep.databricks_run_cost
    )


def test_automation_derived_from_coverage_when_unset():
    a = CostAssumptions.default()
    a.automation_factor = None
    rep = SavingsCalculator().compute([_wf("Low", coverage=80.0)], a)
    assert rep.automation_factor_effective == pytest.approx(0.8)


def test_negative_net_has_no_payback():
    a = CostAssumptions.default()
    # Zero out every recurring saving, keep a run cost → net annual negative.
    a.designer_seats = 0
    a.server_licenses = 0
    a.annual_maintenance_savings = 0
    a.dbu_price = 1.0
    a.dbu_per_workflow_run = 1.0
    a.runs_per_month = 10.0
    a.automation_factor = 0.5
    rep = SavingsCalculator().compute([_wf("High")], a)
    assert rep.net_annual_savings < 0
    assert rep.payback_months is None


def test_empty_estate_is_safe():
    rep = SavingsCalculator().compute([], CostAssumptions.default())
    assert rep.estate.workflow_count == 0
    assert rep.dev_time_saved == 0.0
    assert rep.migration_investment == 0.0
    # No investment → ROI undefined; residual <= 0 → immediate payback.
    assert rep.roi_pct is None
    assert rep.payback_months == 0.0
    assert rep.to_dict()["estate"]["workflow_count"] == 0


def test_to_dict_shape():
    rep = SavingsCalculator().compute([_wf("Low")], CostAssumptions.default())
    d = rep.to_dict()
    assert {"currency", "estate", "assumptions", "lines", "headline", "disclaimer"} <= set(d)
    keys = {line["key"] for line in d["lines"]}
    assert {"dev_time_saved", "migration_investment", "alteryx_license_savings", "databricks_run_cost"} <= keys


# ── config merge + validation ──


def test_from_mapping_coerces_and_overrides():
    a = CostAssumptions.from_mapping({"developer_hourly_rate": "150", "designer_seats": 25, "currency": "EUR"})
    assert a.developer_hourly_rate == 150.0
    assert a.designer_seats == 25.0
    assert a.currency == "EUR"


def test_from_mapping_rejects_negative():
    with pytest.raises(ValueError):
        CostAssumptions.from_mapping({"developer_hourly_rate": -5})


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), 1e309])
def test_from_mapping_rejects_non_finite(bad):
    # NaN/Infinity slip past a plain `< 0` check and serialize as invalid JSON.
    with pytest.raises(ValueError):
        CostAssumptions.from_mapping({"developer_hourly_rate": bad})


def test_from_mapping_automation_bounds():
    assert CostAssumptions.from_mapping({"automation_factor": None}).automation_factor is None
    assert CostAssumptions.from_mapping({"automation_factor": 0.5}).automation_factor == 0.5
    with pytest.raises(ValueError):
        CostAssumptions.from_mapping({"automation_factor": 1.5})


def test_from_mapping_rejects_unknown_hour_anchor():
    with pytest.raises(ValueError):
        CostAssumptions.from_mapping({"hour_anchors": {"Nonsense": 5}})


def test_from_file_json_roundtrip(tmp_path):
    p = tmp_path / "assumptions.json"
    p.write_text('{"designer_seats": 7, "developer_hourly_rate": 200}')
    a = CostAssumptions.from_file(p)
    assert a.designer_seats == 7.0
    assert a.developer_hourly_rate == 200.0
