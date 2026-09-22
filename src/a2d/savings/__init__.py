"""Migration savings / ROI estimator.

A deterministic, offline business-case model: it combines facts the converter
derived from an Alteryx estate (workflow count, per-workflow effort tier, coverage)
with editable cost assumptions to estimate license savings, developer time saved,
net-of-Databricks-run-cost recurring savings, payback and ROI. A planning aid, not
a quote.
"""

from __future__ import annotations

from a2d.savings.calculator import SavingsCalculator, estate_facts
from a2d.savings.model import (
    CostAssumptions,
    EstateFacts,
    SavingsLine,
    SavingsReport,
)

__all__ = [
    "CostAssumptions",
    "EstateFacts",
    "SavingsCalculator",
    "SavingsLine",
    "SavingsReport",
    "estate_facts",
]
