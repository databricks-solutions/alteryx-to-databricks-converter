"""Data models for the migration savings / ROI estimator.

Everything here is deterministic and offline — pure arithmetic over a set of
*configurable* assumptions plus facts derived from the converter's own analysis
(workflow count, per-workflow effort tier, coverage). Nothing calls a model, and
no figure here is a vendor quote: the money defaults are **illustrative
placeholders** meant to be replaced with a customer's real contract numbers.

``CostAssumptions`` mirrors the :class:`~a2d.analyzer.profiler.ProfilerConfig`
contract (``default`` / ``from_mapping`` / ``from_file``) so the CLI ``--config``
file and the App's assumptions form share one merge-and-validate path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from a2d.analyzer.profiler import DEFAULT_HOUR_ANCHORS, TIER_ORDER

# Keys that carry a per-workflow effort tier → hours anchor. Reused from the
# profiler so the effort model has a single source of truth.
_VALID_LEVELS = set(TIER_ORDER)


def _coerce_float(value: object, name: str) -> float:
    """Coerce to a finite, non-negative float or raise ValueError (for API/CLI 4xx).

    Rejects NaN and +/-Infinity: they slip past a plain ``< 0`` check (``nan < 0``
    is False, ``inf`` is not ``< 0``), then propagate into the report and serialize
    as the bare tokens ``NaN`` / ``Infinity`` — invalid JSON that a browser's
    ``JSON.parse`` rejects. Fail loudly at the boundary instead (mapped to 422).
    """
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {value!r}") from None
    if not math.isfinite(out):
        raise ValueError(f"{name} must be a finite number, got {out}")
    if out < 0:
        raise ValueError(f"{name} must be non-negative, got {out}")
    return out


@dataclass
class CostAssumptions:
    """Editable inputs for the savings model. Defaults are illustrative, not quotes.

    Money is in ``currency`` units per year unless noted "one-time". Every field is
    overridable via :meth:`from_mapping` / :meth:`from_file` (CLI ``--config``) or
    the App's assumptions form.
    """

    currency: str = "USD"

    # --- Alteryx licensing retired after migration (annual) ---
    designer_seats: float = 10.0
    designer_cost_per_seat_year: float = 5000.0
    server_licenses: float = 1.0
    server_cost_per_license_year: float = 50000.0

    # --- Developer rewrite time ---
    developer_hourly_rate: float = 100.0  # loaded/blended rate
    # Fraction (0..1) of the manual rewrite the converter automates. When None it
    # is derived from the estate's mean (instance-weighted) coverage, so the number
    # stays grounded in the actual conversion result.
    automation_factor: float | None = None
    review_hours_per_workflow: float = 2.0  # human review of generated code

    # --- Databricks run cost (offsets the savings so ROI is net) ---
    dbu_price: float = 0.55  # $ per DBU (varies by SKU/cloud — placeholder)
    dbu_per_workflow_run: float = 2.0  # estimated DBUs per workflow run
    runs_per_month: float = 20.0  # runs per workflow per month

    # --- Ongoing maintenance / opex reduced by consolidating platforms (annual) ---
    annual_maintenance_savings: float = 15000.0

    # --- Horizon for cumulative / ROI figures ---
    analysis_horizon_years: float = 3.0

    # Effort anchor hours per complexity tier (defaults from the profiler).
    hour_anchors: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_HOUR_ANCHORS))

    @classmethod
    def default(cls) -> CostAssumptions:
        return cls()

    @classmethod
    def from_mapping(cls, data: dict) -> CostAssumptions:
        """Build assumptions by merging a mapping of overrides over the defaults.

        Unknown keys are ignored; recognized numeric keys are coerced and
        validated non-negative. ``automation_factor`` may be ``null`` (derive from
        coverage) or a fraction in ``[0, 1]``. Shared by :meth:`from_file` (CLI) and
        the ``/api/savings`` endpoint (App).
        """
        if not isinstance(data, dict):
            raise ValueError("savings assumptions must be a mapping")

        cfg = cls.default()
        numeric = (
            "designer_seats",
            "designer_cost_per_seat_year",
            "server_licenses",
            "server_cost_per_license_year",
            "developer_hourly_rate",
            "review_hours_per_workflow",
            "dbu_price",
            "dbu_per_workflow_run",
            "runs_per_month",
            "annual_maintenance_savings",
            "analysis_horizon_years",
        )
        for key in numeric:
            if key in data and data[key] is not None:
                setattr(cfg, key, _coerce_float(data[key], key))

        if data.get("currency"):
            cfg.currency = str(data["currency"])

        if "automation_factor" in data:
            af = data["automation_factor"]
            if af is None:
                cfg.automation_factor = None
            else:
                val = _coerce_float(af, "automation_factor")
                if val > 1.0:
                    raise ValueError(f"automation_factor must be in [0, 1], got {val}")
                cfg.automation_factor = val

        if data.get("hour_anchors"):
            anchors = data["hour_anchors"]
            if not isinstance(anchors, dict):
                raise ValueError("hour_anchors must be a mapping of tier -> hours")
            bad = set(anchors) - _VALID_LEVELS
            if bad:
                raise ValueError(f"unknown hour_anchors tier(s): {sorted(bad)}; must be one of {sorted(_VALID_LEVELS)}")
            cfg.hour_anchors.update({k: _coerce_float(v, f"hour_anchors[{k}]") for k, v in anchors.items()})

        return cfg

    @classmethod
    def from_file(cls, path: Path) -> CostAssumptions:
        """Load overrides from a YAML or JSON file, merged over the defaults."""
        text = Path(path).read_text(encoding="utf-8")
        if path.suffix.lower() in (".yaml", ".yml"):
            try:
                import yaml
            except ImportError as exc:  # pragma: no cover - env-dependent
                raise ImportError("PyYAML is required to read a YAML savings config") from exc
            data = yaml.safe_load(text) or {}
        else:
            import json

            data = json.loads(text) or {}
        return cls.from_mapping(data)

    def to_dict(self) -> dict:
        return {
            "currency": self.currency,
            "designer_seats": self.designer_seats,
            "designer_cost_per_seat_year": self.designer_cost_per_seat_year,
            "server_licenses": self.server_licenses,
            "server_cost_per_license_year": self.server_cost_per_license_year,
            "developer_hourly_rate": self.developer_hourly_rate,
            "automation_factor": self.automation_factor,
            "review_hours_per_workflow": self.review_hours_per_workflow,
            "dbu_price": self.dbu_price,
            "dbu_per_workflow_run": self.dbu_per_workflow_run,
            "runs_per_month": self.runs_per_month,
            "annual_maintenance_savings": self.annual_maintenance_savings,
            "analysis_horizon_years": self.analysis_horizon_years,
            "hour_anchors": dict(self.hour_anchors),
        }


@dataclass
class EstateFacts:
    """Facts the converter derived from the workflows, grounding the savings math."""

    workflow_count: int
    total_manual_hours: float  # sum of per-workflow effort-tier anchor hours
    hours_by_level: dict[str, float]  # tier -> summed anchor hours
    workflows_by_level: dict[str, int]  # tier -> count
    mean_coverage_pct: float  # node-instance-weighted mean coverage across estate

    def to_dict(self) -> dict:
        return {
            "workflow_count": self.workflow_count,
            "total_manual_hours": round(self.total_manual_hours, 1),
            "hours_by_level": {k: round(v, 1) for k, v in self.hours_by_level.items()},
            "workflows_by_level": dict(self.workflows_by_level),
            "mean_coverage_pct": round(self.mean_coverage_pct, 1),
        }


@dataclass
class SavingsLine:
    """One labeled line in the savings breakdown."""

    key: str
    label: str
    amount: float
    kind: str  # "one_time" | "annual"
    direction: str  # "saving" | "cost" | "investment"

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "amount": round(self.amount, 2),
            "kind": self.kind,
            "direction": self.direction,
        }


@dataclass
class SavingsReport:
    """A deterministic migration business case — a planning estimate, not a quote."""

    currency: str
    estate: EstateFacts
    assumptions: CostAssumptions
    lines: list[SavingsLine]

    # Derived headline figures
    automation_factor_effective: float
    dev_hours_avoided: float
    dev_time_saved: float  # one-time $
    migration_investment: float  # one-time $
    alteryx_license_savings: float  # annual $
    maintenance_savings: float  # annual $
    databricks_run_cost: float  # annual $
    net_annual_savings: float  # annual $
    cumulative_net: float  # over horizon, incl. one-time
    payback_months: float | None  # None when it never pays back on recurring alone
    roi_pct: float | None  # None when there is no migration investment to divide by

    disclaimer: str = (
        "Planning estimate only — not a quote or an audit. Figures combine facts "
        "derived from your workflows with editable cost assumptions; replace the "
        "defaults with your real contract and rate numbers."
    )

    def to_dict(self) -> dict:
        return {
            "currency": self.currency,
            "estate": self.estate.to_dict(),
            "assumptions": self.assumptions.to_dict(),
            "lines": [line.to_dict() for line in self.lines],
            "headline": {
                "automation_factor_effective": round(self.automation_factor_effective, 3),
                "dev_hours_avoided": round(self.dev_hours_avoided, 1),
                "dev_time_saved": round(self.dev_time_saved, 2),
                "migration_investment": round(self.migration_investment, 2),
                "alteryx_license_savings": round(self.alteryx_license_savings, 2),
                "maintenance_savings": round(self.maintenance_savings, 2),
                "databricks_run_cost": round(self.databricks_run_cost, 2),
                "net_annual_savings": round(self.net_annual_savings, 2),
                "cumulative_net": round(self.cumulative_net, 2),
                "payback_months": (round(self.payback_months, 1) if self.payback_months is not None else None),
                "roi_pct": (round(self.roi_pct, 1) if self.roi_pct is not None else None),
            },
            "disclaimer": self.disclaimer,
        }
