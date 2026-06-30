"""Actionable remediation hints for common conversion warnings."""

from __future__ import annotations

# Maps warning substrings to (next_step, category) tuples.
# Matched case-insensitively against warning messages.
REMEDIATION_HINTS: dict[str, tuple[str, str]] = {
    # ── Spatial tools (generic pattern matches all spatial tool types) ─
    "spatial": (
        "Use Databricks Mosaic library (dbdemos.install('mosaic')) for spatial operations",
        "spatial",
    ),
    "Geocoder": (
        "Use a geocoding API (e.g. Databricks marketplace geocoding) as a UDF",
        "spatial",
    ),
    # ── Expression issues ──────────────────────────────────────────────
    "expression parse failed": (
        "Review the original Alteryx expression and manually translate to PySpark",
        "expression",
    ),
    "PLACEHOLDER": (
        "The PLACEHOLDER value must be replaced with the correct PySpark expression",
        "expression",
    ),
    "Unknown function": (
        "Check pyspark.sql.functions for an equivalent, or implement as a UDF",
        "expression",
    ),
    # ── Join issues ─────────────────────────────────────────────────────
    "no join keys found": (
        "Inspect the original workflow and add the correct join condition",
        "join",
    ),
    "F.lit(True)": (
        "Replace F.lit(True) with the actual join condition from the Alteryx workflow",
        "join",
    ),
    # ── Unsupported tools ──────────────────────────────────────────────
    "Unsupported": (
        "Manual implementation required — check Databricks documentation for equivalent",
        "unsupported",
    ),
    # ── Predictive / ML (generic — matches all predictive tool names) ─
    "manual conversion to Spark MLlib": (
        "Use spark.ml (MLlib) or pandas UDF with scikit-learn for ML operations",
        "predictive",
    ),
    "ARIMA": (
        "Use Prophet on Databricks or spark-ts for time series forecasting",
        "predictive",
    ),
    # ── Reporting tools ────────────────────────────────────────────────
    "Chart": (
        "Use Databricks notebook visualizations or matplotlib/plotly for charts",
        "reporting",
    ),
    "Report": (
        "Use Databricks dashboards or notebook markdown cells for reporting",
        "reporting",
    ),
    "EmailOutput": (
        "Use Databricks workflows with email notifications, or a webhook",
        "reporting",
    ),
    # ── Developer tools ────────────────────────────────────────────────
    "PythonTool": (
        "Embed the Python code directly in the notebook — may need pandas->PySpark conversion",
        "developer",
    ),
    "RunCommand": (
        "Use %sh magic commands or dbutils.notebook.run() for external commands",
        "developer",
    ),
    # ── Interface / Macro ──────────────────────────────────────────────
    "Macro": (
        "Convert macro parameters to notebook widgets (dbutils.widgets)",
        "interface",
    ),
    # ── Connectivity ───────────────────────────────────────────────────
    "ODBC": (
        "Replace ODBC with Unity Catalog external tables or JDBC spark.read",
        "connectivity",
    ),
    "Syntax error": (
        "The generated Python has a syntax issue — review and fix manually",
        "syntax",
    ),
}


def get_hint(warning: str) -> tuple[str, str] | None:
    """Look up a remediation hint for a warning message.

    Returns (next_step, category) or None if no match.
    """
    warning_lower = warning.lower()
    for pattern, hint in REMEDIATION_HINTS.items():
        if pattern.lower() in warning_lower:
            return hint
    return None


def enrich_warnings(warnings: list[str]) -> list[dict]:
    """Enrich a list of warning strings with remediation hints.

    Returns a list of dicts: {"message": str, "hint": str | None, "category": str | None}.
    """
    enriched = []
    for w in warnings:
        hint = get_hint(w)
        enriched.append(
            {
                "message": w,
                "hint": hint[0] if hint else None,
                "category": hint[1] if hint else None,
            }
        )
    return enriched
