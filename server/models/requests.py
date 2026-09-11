"""Pydantic request models for the API."""

from __future__ import annotations

import re
from dataclasses import dataclass

from fastapi import Form, HTTPException

# Unity Catalog catalog/schema names: letters, digits, underscore; a leading
# letter or underscore. These values are interpolated into generated code
# (saveAsTable("catalog.schema.table")) and YAML, so an unvalidated value with
# quotes/newlines could break or inject into the generated artifact.
_UC_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_uc_identifier(value: str, field_name: str) -> str:
    value = (value or "").strip()
    if not _UC_IDENTIFIER_RE.match(value):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid {field_name} {value!r}: use a Unity Catalog identifier "
                "(letters, digits, underscore; starting with a letter or underscore)."
            ),
        )
    return value


@dataclass
class ConversionOptions:
    """Shared conversion form parameters for single and batch endpoints.

    Note: ``output_format`` was removed in the multi-format refactor — every
    request now produces all output formats (pyspark, dlt, sql, lakeflow,
    designer).
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
        catalog_name=_validate_uc_identifier(catalog_name, "catalog_name"),
        schema_name=_validate_uc_identifier(schema_name, "schema_name"),
        include_comments=include_comments,
        include_expression_audit=include_expression_audit,
        include_performance_hints=include_performance_hints,
        generate_ddl=generate_ddl,
        generate_dab=generate_dab,
        expand_macros=expand_macros,
    )
