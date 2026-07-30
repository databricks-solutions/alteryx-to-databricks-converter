"""Data-profiling pass — infer schema/types/null-rates from sample data.

Given a sample input DataFrame (or a CSV path), produce a :class:`DataProfile`
describing each column: an inferred logical type, null rate, distinct count,
and (for numeric/temporal columns) min/max. The profile also emits a suggested
Spark DDL type per column.

Why this exists: the converter's generated ``read`` calls today infer types at
runtime from whatever the source happens to contain. Profiling the *sample* data
up front makes source typing explicit and deterministic — it feeds better read
schemas and gives ``a2d verify`` a typed baseline to compare against, rather than
relying on pandas' incidental CSV dtype inference.

Pure pandas, no Spark/JVM dependency — runs everywhere and is fully testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

# Logical types we classify columns into (target-agnostic).
LogicalType = str  # "integer" | "double" | "boolean" | "date" | "timestamp" | "string" | "empty"

# Logical type → Spark SQL DDL type.
_SPARK_DDL: dict[str, str] = {
    "integer": "BIGINT",
    "double": "DOUBLE",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "timestamp": "TIMESTAMP",
    "string": "STRING",
    "empty": "STRING",  # all-null column → default to STRING
}


@dataclass
class ColumnProfile:
    """Inferred profile for a single column."""

    name: str
    logical_type: LogicalType
    spark_type: str
    total_count: int = 0
    null_count: int = 0
    distinct_count: int = 0
    min_value: Any = None
    max_value: Any = None
    sample_values: list[Any] = field(default_factory=list)

    @property
    def null_rate(self) -> float:
        return (self.null_count / self.total_count) if self.total_count else 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "logical_type": self.logical_type,
            "spark_type": self.spark_type,
            "total_count": self.total_count,
            "null_count": self.null_count,
            "null_rate": round(self.null_rate, 4),
            "distinct_count": self.distinct_count,
            "min_value": None if self.min_value is None else str(self.min_value),
            "max_value": None if self.max_value is None else str(self.max_value),
        }


@dataclass
class DataProfile:
    """Profile of a tabular dataset."""

    source: str
    row_count: int
    columns: list[ColumnProfile] = field(default_factory=list)

    def spark_schema_ddl(self) -> str:
        """Return a Spark ``StructType`` DDL string, e.g. ``a BIGINT, b STRING``."""
        return ", ".join(f"`{c.name}` {c.spark_type}" for c in self.columns)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "row_count": self.row_count,
            "spark_schema_ddl": self.spark_schema_ddl(),
            "columns": [c.to_dict() for c in self.columns],
        }


def _infer_logical_type(series: pd.Series) -> LogicalType:
    """Infer a logical type from a column's non-null values.

    Object/string columns are re-examined value-by-value (CSV reads everything as
    strings), so "1"/"2" is recognized as integer, "1.5" as double, and
    "2024-01-01" as date/timestamp — matching how a warehouse would type a
    text column on ingest.
    """
    import pandas as pd

    non_null = series.dropna()
    if len(non_null) == 0:
        return "empty"

    # Trust already-typed pandas columns first.
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_float_dtype(series):
        return "double"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "timestamp"

    # Object/string: sniff the actual values.
    values = non_null.astype(str).str.strip()

    if values.str.lower().isin(("true", "false")).all():
        return "boolean"

    as_int = pd.to_numeric(values, errors="coerce")
    if as_int.notna().all() and (as_int == as_int.round()).all():
        return "integer"

    as_num = pd.to_numeric(values, errors="coerce")
    if as_num.notna().all():
        return "double"

    # Date vs timestamp: parse, then check whether any time component is present.
    as_dt = pd.to_datetime(values, errors="coerce", format="mixed")
    if as_dt.notna().all():
        has_time = (as_dt.dt.hour.ne(0) | as_dt.dt.minute.ne(0) | as_dt.dt.second.ne(0)).any()
        return "timestamp" if has_time else "date"

    return "string"


def _min_max(series: pd.Series, logical_type: LogicalType) -> tuple[Any, Any]:
    """Return (min, max) for orderable types, else (None, None)."""
    import pandas as pd

    non_null = series.dropna()
    if len(non_null) == 0:
        return None, None
    try:
        if logical_type in ("integer", "double"):
            nums = pd.to_numeric(non_null.astype(str).str.strip(), errors="coerce").dropna()
            if len(nums) == 0:
                return None, None
            lo, hi = nums.min(), nums.max()
            if logical_type == "integer":
                return int(lo), int(hi)
            return float(lo), float(hi)
        if logical_type in ("date", "timestamp"):
            dts = pd.to_datetime(non_null.astype(str).str.strip(), errors="coerce", format="mixed").dropna()
            if len(dts) == 0:
                return None, None
            return dts.min(), dts.max()
    except (ValueError, TypeError):
        return None, None
    return None, None


def profile_dataframe(df: pd.DataFrame, *, source: str = "<dataframe>", max_samples: int = 5) -> DataProfile:
    """Build a :class:`DataProfile` from a pandas DataFrame."""
    columns: list[ColumnProfile] = []
    total = len(df)
    for name in df.columns:
        series = df[name]
        logical = _infer_logical_type(series)
        lo, hi = _min_max(series, logical)
        non_null = series.dropna()
        columns.append(
            ColumnProfile(
                name=str(name),
                logical_type=logical,
                spark_type=_SPARK_DDL.get(logical, "STRING"),
                total_count=total,
                null_count=int(series.isna().sum()),
                distinct_count=int(non_null.nunique()),
                min_value=lo,
                max_value=hi,
                sample_values=[str(v) for v in non_null.unique()[:max_samples]],
            )
        )
    return DataProfile(source=source, row_count=total, columns=columns)


def profile_csv(path: str, *, max_samples: int = 5) -> DataProfile:
    """Load a CSV and profile it (keeps everything as strings for honest sniffing)."""
    import pandas as pd

    # dtype=str so we classify from the raw text, mirroring warehouse ingest.
    df = pd.read_csv(path, dtype=str, keep_default_na=True)
    return profile_dataframe(df, source=path, max_samples=max_samples)
