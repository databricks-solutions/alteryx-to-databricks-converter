"""Pydantic request models for the API."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Form


@dataclass
class ConversionOptions:
    """Shared conversion form parameters for single and batch endpoints.

    Note: ``output_format`` was removed in the multi-format refactor — every
    request now produces all four output formats (pyspark, dlt, sql, lakeflow).
    """

    catalog_name: str
    schema_name: str
    include_comments: bool
    include_expression_audit: bool
    include_performance_hints: bool
    generate_ddl: bool
    generate_dab: bool
    expand_macros: bool


def conversion_options(
    catalog_name: str = Form("main"),
    schema_name: str = Form("default"),
    include_comments: bool = Form(True),
    include_expression_audit: bool = Form(False),
    include_performance_hints: bool = Form(False),
    generate_ddl: bool = Form(False),
    generate_dab: bool = Form(False),
    expand_macros: bool = Form(False),
) -> ConversionOptions:
    """FastAPI dependency that collects shared conversion form params."""
    return ConversionOptions(
        catalog_name=catalog_name,
        schema_name=schema_name,
        include_comments=include_comments,
        include_expression_audit=include_expression_audit,
        include_performance_hints=include_performance_hints,
        generate_ddl=generate_ddl,
        generate_dab=generate_dab,
        expand_macros=expand_macros,
    )
