"""Semantic equivalence verification for a2d conversions.

The converter proves *syntactic* validity today (does the generated code parse?)
and estimates *confidence* heuristically. This package proves *semantic*
equivalence: given sample input data, does the generated pipeline produce the
same result as the original Alteryx workflow would?

Two things make that possible without an Alteryx license:

* **Pandas reference executor** (:mod:`a2d.verification.reference`) — an
  independent second implementation of the IR semantics in pandas. It runs
  everywhere (no JVM) and its agreement with the generated PySpark is genuine
  equivalence signal. It is also the executor used for *golden-file* mode, where
  the user supplies the expected output exported from Alteryx once.
* **Parity engine** (:mod:`a2d.verification.parity`) — a pure-pandas DataFrame
  diff (schema, row count, order-insensitive row equality, per-column
  value compare with numeric tolerance, aggregate fingerprint).

The optional **Spark backend** (:mod:`a2d.verification.spark_backend`) executes
the generated PySpark where a JVM is available (Databricks / CI) and reports a
clean ``spark_unavailable`` status otherwise, so ``a2d verify`` degrades
gracefully on a laptop.
"""

from __future__ import annotations

from a2d.verification.parity import ColumnParity, ParityReport, compare_frames
from a2d.verification.profiling import (
    ColumnProfile,
    DataProfile,
    profile_csv,
    profile_dataframe,
)
from a2d.verification.reference import ReferenceExecutor, ReferenceResult
from a2d.verification.runner import VerificationResult, verify_workflow
from a2d.verification.spark_backend import SparkBackend, spark_available

__all__ = [
    "ColumnParity",
    "ColumnProfile",
    "DataProfile",
    "ParityReport",
    "ReferenceExecutor",
    "ReferenceResult",
    "SparkBackend",
    "VerificationResult",
    "compare_frames",
    "profile_csv",
    "profile_dataframe",
    "spark_available",
    "verify_workflow",
]
