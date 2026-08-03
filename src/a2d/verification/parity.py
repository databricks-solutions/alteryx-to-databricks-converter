"""Parity engine — compare two tabular results for semantic equivalence.

Pure pandas, no Spark/JVM dependency, so it runs everywhere and is fully unit
testable. Given two :class:`pandas.DataFrame` results (e.g. the expected output
exported from Alteryx and the output of a generated pipeline), it reports:

* **schema parity** — column set and dtype family compatibility,
* **row-count parity**,
* **row-set parity** — order-insensitive equality of the full row multiset,
* **per-column parity** — value comparison with numeric tolerance and
  null-aware equality, plus a small sample of mismatches for debugging.

The result is a structured :class:`ParityReport` with an overall ``passed``
verdict and a numeric ``parity_score`` (0..1) so callers (CLI, CI) can gate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

# Default absolute+relative tolerance for floating-point column comparison.
_DEFAULT_ABS_TOL = 1e-9
_DEFAULT_REL_TOL = 1e-6
# How many example mismatches to retain per column (for human debugging).
_MAX_MISMATCH_SAMPLES = 5


@dataclass
class ColumnParity:
    """Per-column comparison result."""

    column: str
    present_in_both: bool
    dtype_expected: str = ""
    dtype_actual: str = ""
    dtype_compatible: bool = True
    mismatch_count: int = 0
    total_compared: int = 0
    sample_mismatches: list[tuple[Any, Any]] = field(default_factory=list)

    @property
    def matches(self) -> bool:
        return self.present_in_both and self.dtype_compatible and self.mismatch_count == 0


@dataclass
class ParityReport:
    """Structured result of comparing an expected vs. actual DataFrame."""

    passed: bool
    parity_score: float  # 0.0 .. 1.0
    # Schema
    expected_columns: list[str] = field(default_factory=list)
    actual_columns: list[str] = field(default_factory=list)
    missing_columns: list[str] = field(default_factory=list)  # expected but not produced
    extra_columns: list[str] = field(default_factory=list)  # produced but not expected
    # Rows
    expected_row_count: int = 0
    actual_row_count: int = 0
    row_count_match: bool = False
    row_set_match: bool = False
    unmatched_expected_rows: int = 0
    unmatched_actual_rows: int = 0
    # Columns
    column_parities: list[ColumnParity] = field(default_factory=list)
    # Free-text notes (e.g. why a comparison was degraded)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        return (
            f"{verdict} (score {self.parity_score:.2f}) — "
            f"cols {len(self.actual_columns)}/{len(self.expected_columns)}, "
            f"rows {self.actual_row_count}/{self.expected_row_count}, "
            f"row-set {'match' if self.row_set_match else 'differ'}"
        )

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "parity_score": round(self.parity_score, 4),
            "schema": {
                "expected_columns": self.expected_columns,
                "actual_columns": self.actual_columns,
                "missing_columns": self.missing_columns,
                "extra_columns": self.extra_columns,
            },
            "rows": {
                "expected_row_count": self.expected_row_count,
                "actual_row_count": self.actual_row_count,
                "row_count_match": self.row_count_match,
                "row_set_match": self.row_set_match,
                "unmatched_expected_rows": self.unmatched_expected_rows,
                "unmatched_actual_rows": self.unmatched_actual_rows,
            },
            "columns": [
                {
                    "column": c.column,
                    "present_in_both": c.present_in_both,
                    "dtype_expected": c.dtype_expected,
                    "dtype_actual": c.dtype_actual,
                    "dtype_compatible": c.dtype_compatible,
                    "mismatch_count": c.mismatch_count,
                    "total_compared": c.total_compared,
                    "matches": c.matches,
                }
                for c in self.column_parities
            ],
            "notes": self.notes,
        }


def _dtype_family(dtype) -> str:
    """Coarse dtype family so int64 vs. int32 (etc.) are treated as compatible."""
    import pandas as pd

    if pd.api.types.is_bool_dtype(dtype):
        return "bool"
    if pd.api.types.is_integer_dtype(dtype):
        return "number"
    if pd.api.types.is_float_dtype(dtype):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "datetime"
    if pd.api.types.is_string_dtype(dtype) or pd.api.types.is_object_dtype(dtype):
        return "string"
    return str(dtype)


def _is_null(v: Any) -> bool:
    """Scalar null test covering None, float NaN, pd.NaT, and pd.NA.

    Uses ``pd.isna`` (which recognizes ``pd.NA`` from nullable/string dtypes)
    but guards against array-like inputs, where ``pd.isna`` returns an array
    and would raise in a boolean context.
    """
    import pandas as pd

    if v is None:
        return True
    try:
        result = pd.isna(v)
    except (TypeError, ValueError):
        return False
    # pd.isna returns an ndarray for array-like input; only a scalar bool means null.
    return bool(result) if isinstance(result, bool) else False


def _values_equal(a: Any, b: Any, abs_tol: float, rel_tol: float) -> bool:
    """Null-aware, numeric-tolerant scalar equality."""
    a_null, b_null = _is_null(a), _is_null(b)
    if a_null or b_null:
        return a_null and b_null

    # Numeric compare with tolerance (covers int/float cross-type).
    if (
        isinstance(a, (int | float))
        and isinstance(b, (int | float))
        and not isinstance(a, bool)
        and not isinstance(b, bool)
    ):
        return math.isclose(float(a), float(b), abs_tol=abs_tol, rel_tol=rel_tol)

    # Fall back to string-normalized equality (handles "1" vs 1 from CSV reads).
    return str(a).strip() == str(b).strip()


def _rowset_float_ndigits(rel_tol: float) -> int:
    """Decimal places to quantize floats to for row-set comparison, from rel_tol."""
    if rel_tol <= 0:
        return 12
    # e.g. rel_tol 1e-6 -> 6 places; clamp to a sane range.
    return max(1, min(12, round(-math.log10(rel_tol))))


def _normalize_for_rowset(df: pd.DataFrame, *, float_ndigits: int = 6) -> pd.DataFrame:
    """Stringify + strip so row-set comparison is dtype-, whitespace-, and
    float-tolerance-robust. Non-integer floats are quantized to
    ``float_ndigits`` places so values within tolerance collapse to the same key.
    """

    def _norm(v: Any) -> str:
        if _is_null(v):
            return "\x00NULL\x00"
        if isinstance(v, float):
            # Quantize consistently so tolerance-equal floats collapse to the
            # same key AND an integer-valued float ("1.0") matches an int ("1").
            r = round(v, float_ndigits)
            return str(int(r)) if r == int(r) else format(r, f".{float_ndigits}f")
        return str(v).strip()

    return df.map(_norm)


def compare_frames(
    expected: pd.DataFrame,
    actual: pd.DataFrame,
    *,
    abs_tol: float = _DEFAULT_ABS_TOL,
    rel_tol: float = _DEFAULT_REL_TOL,
    ignore_row_order: bool = True,
) -> ParityReport:
    """Compare ``actual`` against ``expected`` and return a :class:`ParityReport`.

    The comparison is intentionally lenient about things that don't affect
    semantic equivalence (column order, int-vs-float, whitespace, row order when
    ``ignore_row_order``) and strict about things that do (column set, row
    multiset, per-cell values within tolerance).
    """

    notes: list[str] = []
    expected_cols = list(expected.columns)
    actual_cols = list(actual.columns)
    exp_set, act_set = set(expected_cols), set(actual_cols)
    missing = [c for c in expected_cols if c not in act_set]
    extra = [c for c in actual_cols if c not in exp_set]
    common = [c for c in expected_cols if c in act_set]

    # -- Schema/dtype parity --
    column_parities: list[ColumnParity] = []
    for c in expected_cols:
        if c not in act_set:
            column_parities.append(ColumnParity(column=c, present_in_both=False, dtype_expected=str(expected[c].dtype)))
            continue
        de, da = _dtype_family(expected[c].dtype), _dtype_family(actual[c].dtype)
        column_parities.append(
            ColumnParity(
                column=c,
                present_in_both=True,
                dtype_expected=str(expected[c].dtype),
                dtype_actual=str(actual[c].dtype),
                dtype_compatible=(de == da),
            )
        )

    # -- Row-count parity --
    exp_n, act_n = len(expected), len(actual)
    row_count_match = exp_n == act_n

    # -- Row-set parity (order-insensitive multiset over common columns) --
    row_set_match = False
    unmatched_expected = exp_n
    unmatched_actual = act_n
    if common:
        ndigits = _rowset_float_ndigits(rel_tol)
        en = _normalize_for_rowset(expected[common], float_ndigits=ndigits)
        an = _normalize_for_rowset(actual[common], float_ndigits=ndigits)
        exp_counts = en.value_counts(dropna=False)
        act_counts = an.value_counts(dropna=False)
        # Multiset difference in both directions.
        all_rows = exp_counts.index.union(act_counts.index)
        unmatched_expected = 0
        unmatched_actual = 0
        for row in all_rows:
            e = int(exp_counts.get(row, 0))
            a = int(act_counts.get(row, 0))
            if e > a:
                unmatched_expected += e - a
            elif a > e:
                unmatched_actual += a - e
        row_set_match = unmatched_expected == 0 and unmatched_actual == 0
    else:
        notes.append("No columns in common — cannot compare row values.")

    # -- Per-column value parity (only meaningful when row order is aligned OR
    #    both sides sorted). We compare column-wise on a sorted, reset copy so a
    #    matching row-set yields zero cell mismatches regardless of order. --
    if common and ignore_row_order and exp_n == act_n and exp_n > 0:
        try:
            e_sorted = expected[common].sort_values(by=common, kind="stable").reset_index(drop=True)
            a_sorted = actual[common].sort_values(by=common, kind="stable").reset_index(drop=True)
        except TypeError:
            # Unsortable (mixed types) — skip per-cell, rely on row-set result.
            e_sorted = a_sorted = None
            notes.append("Columns not sortable — per-column cell comparison skipped.")
    elif common and exp_n == act_n and exp_n > 0:
        e_sorted = expected[common].reset_index(drop=True)
        a_sorted = actual[common].reset_index(drop=True)
    else:
        e_sorted = a_sorted = None

    cell_comparison_ran = e_sorted is not None and a_sorted is not None
    if e_sorted is not None and a_sorted is not None:
        cp_by_name = {cp.column: cp for cp in column_parities}
        for c in common:
            cp = cp_by_name[c]
            mismatches = 0
            samples: list[tuple[Any, Any]] = []
            ecol, acol = e_sorted[c].tolist(), a_sorted[c].tolist()
            cp.total_compared = len(ecol)
            for ev, av in zip(ecol, acol, strict=False):
                if not _values_equal(ev, av, abs_tol, rel_tol):
                    mismatches += 1
                    if len(samples) < _MAX_MISMATCH_SAMPLES:
                        samples.append((ev, av))
            cp.mismatch_count = mismatches
            cp.sample_mismatches = samples

    # -- Overall score + verdict --
    schema_ok = not missing and not extra
    score_parts: list[float] = []
    # Column presence (fraction of expected cols produced, penalize extras).
    if expected_cols:
        col_score = len(common) / len(expected_cols)
        if extra:
            col_score *= len(expected_cols) / (len(expected_cols) + len(extra))
        score_parts.append(col_score)
    # Row-set score.
    denom = max(exp_n, act_n, 1)
    matched_rows = denom - max(unmatched_expected, unmatched_actual)
    score_parts.append(max(0.0, matched_rows / denom))
    # Dtype compatibility over common cols.
    if common:
        compat = sum(1 for cp in column_parities if cp.present_in_both and cp.dtype_compatible)
        score_parts.append(compat / len(common))

    parity_score = sum(score_parts) / len(score_parts) if score_parts else 0.0

    cell_ok = all(cp.mismatch_count == 0 for cp in column_parities if cp.present_in_both)
    # When the per-cell comparison ran (aligned row counts + sortable columns),
    # it is the authoritative, tolerance-correct check. The string-quantized
    # row-set match can spuriously differ for floats near a rounding boundary,
    # so don't let it alone fail a run whose cells all match within tolerance —
    # reserve row_set_match as the gate only when per-cell couldn't run.
    if cell_comparison_ran:
        rows_ok = row_count_match and cell_ok
    else:
        rows_ok = row_count_match and row_set_match
    passed = bool(schema_ok and rows_ok)

    if cell_comparison_ran and cell_ok and not row_set_match:
        notes.append(
            "Row-set key differs only by float-rounding near a boundary; "
            "per-cell tolerant comparison matched, so treated as equivalent."
        )

    return ParityReport(
        passed=passed,
        parity_score=parity_score,
        expected_columns=expected_cols,
        actual_columns=actual_cols,
        missing_columns=missing,
        extra_columns=extra,
        expected_row_count=exp_n,
        actual_row_count=act_n,
        row_count_match=row_count_match,
        row_set_match=row_set_match,
        unmatched_expected_rows=unmatched_expected,
        unmatched_actual_rows=unmatched_actual,
        column_parities=column_parities,
        notes=notes,
    )
