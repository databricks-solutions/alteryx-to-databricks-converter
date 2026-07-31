"""Structural validation for generated Lakeflow Designer ``.designer.ipynb`` files.

The :class:`~a2d.generators.designer.DesignerGenerator` emits a notebook that
Lakeflow Designer imports and rehydrates into a visual canvas. A file can be
*generated* fine yet still fail to render if it violates the import contract
(malformed JSON, an annotation that isn't parseable YAML, a cell body that isn't
valid Python, a missing per-cell ``nuid``, dangling wiring, …).

This module checks that contract *offline* — no Databricks workspace required —
so it can run in CI on every generated file. It is the automatable half of the
Q1 "Designer round-trip validation" item; the other half (an actual import into
a live Designer canvas) is exercised by a skip-guarded integration test.

The checks mirror the documented import requirements
(``docs/lakeflow-designer-generator-design.md``): valid ipynb JSON, required
notebook/cell metadata, unique ``nuid`` per cell, a well-formed YAML annotation
per cell carrying ``id``/``template``/``input``, a Python-parseable body, and
``input[]`` references that resolve to cells defined in the file.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field

_NOTEBOOK_META_KEY = "application/vnd.databricks.v1+notebook"
_CELL_META_KEY = "application/vnd.databricks.v1+cell"

# Allowed config keys per operator template. Designer enforces
# ``additionalProperties: false`` on each operator's config, so emitting any key
# not in this set fails import with "config must NOT have additional properties".
# Sourced from real .designer.ipynb exports (see
# docs/lakeflow-designer-generator-design.md §3.x). Operators not listed here are
# not config-checked (unknown templates only get structural checks).
_OPERATOR_CONFIG_KEYS: dict[str, set[str]] = {
    "source": {"file_source", "table_source"},
    "output": {"catalog", "schema", "table_name"},
    "filter": {"condition"},
    "join": {"join_type", "join_conditions", "expressions"},
    "aggregate": {"group_bys", "aggregations"},
    "sort": {"sort_expressions"},
    "limit": {"limit"},
    "combine": {"operator", "quantifier"},
    "transform": {"expressions"},
    "pivot": {
        "mode", "pivot_column", "value_column", "agg_fn", "null_behavior",
        "unpivot_columns", "exclude_columns", "id_columns", "value_columns",
        "key_column_name", "value_column_name", "key_name", "value_name",
    },
    "python": {"code"},
    "sql": {"query"},
    "ai_function": {"expressions"},
    "markdown": {"md"},
    "group": set(),
}


@dataclass
class DesignerValidationResult:
    """Outcome of validating a ``.designer.ipynb`` structurally."""

    is_valid: bool
    cell_count: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.is_valid


def _split_annotation_and_body(source: str) -> tuple[str | None, str]:
    """Return (annotation_yaml, body) for a Designer cell's source string.

    The annotation is the first triple-quoted docstring; the body is whatever
    follows it. Returns (None, source) if there's no leading docstring.
    """
    stripped = source.lstrip()
    if not stripped.startswith('"""'):
        return None, source
    # Find the closing triple-quote after the opening one.
    rest = stripped[3:]
    end = rest.find('"""')
    if end == -1:
        return None, source
    annotation = rest[:end]
    body = rest[end + 3 :]
    return annotation, body


def validate_designer_notebook(content: str) -> DesignerValidationResult:
    """Validate a ``.designer.ipynb`` (as a JSON string) against the import contract."""
    import yaml

    errors: list[str] = []
    warnings: list[str] = []

    # 1. Valid notebook JSON.
    try:
        nb = json.loads(content)
    except json.JSONDecodeError as exc:
        return DesignerValidationResult(is_valid=False, errors=[f"Not valid JSON: {exc}"])

    if not isinstance(nb, dict):
        return DesignerValidationResult(is_valid=False, errors=["Notebook root is not an object"])

    # 2. nbformat + notebook-level Databricks metadata.
    if nb.get("nbformat") != 4:
        errors.append(f"nbformat must be 4, got {nb.get('nbformat')!r}")
    meta = nb.get("metadata", {})
    if _NOTEBOOK_META_KEY not in meta:
        errors.append(f"Missing required notebook metadata key '{_NOTEBOOK_META_KEY}'")

    cells = nb.get("cells", [])
    if not isinstance(cells, list):
        return DesignerValidationResult(is_valid=False, errors=["'cells' is not a list"])

    # 3. Per-cell checks: metadata + nuid, annotation YAML, body Python.
    seen_nuids: set[str] = set()
    defined_ids: set[str] = set()
    # (cell_index, referenced_node_id) pairs to check after all ids are known.
    input_refs: list[tuple[int, str]] = []

    for i, cell in enumerate(cells):
        source = "".join(cell.get("source", []))
        cell_meta = cell.get("metadata", {}).get(_CELL_META_KEY)
        if cell_meta is None:
            errors.append(f"Cell {i}: missing required '{_CELL_META_KEY}' metadata")
        else:
            nuid = cell_meta.get("nuid")
            if not nuid:
                errors.append(f"Cell {i}: missing/empty nuid")
            elif nuid in seen_nuids:
                errors.append(f"Cell {i}: duplicate nuid {nuid!r}")
            else:
                seen_nuids.add(nuid)

        annotation, body = _split_annotation_and_body(source)
        if annotation is None:
            errors.append(f"Cell {i}: no annotation docstring found")
            continue

        # Annotation must be valid, complete YAML.
        try:
            parsed = yaml.safe_load(annotation)
        except yaml.YAMLError as exc:
            errors.append(f"Cell {i}: annotation is not valid YAML: {exc}")
            continue
        if not isinstance(parsed, dict):
            errors.append(f"Cell {i}: annotation did not parse to a mapping")
            continue

        for key in ("id", "template", "input"):
            if key not in parsed:
                errors.append(f"Cell {i}: annotation missing required key '{key}'")
        if "id" in parsed:
            defined_ids.add(str(parsed["id"]))
        for inp in parsed.get("input", []) or []:
            if isinstance(inp, dict) and "node" in inp:
                input_refs.append((i, str(inp["node"])))

        # Per-operator config-key check: Designer enforces additionalProperties:
        # false, so any config key outside the operator's allowed set fails import
        # ("config must NOT have additional properties"). Catch it offline.
        template = parsed.get("template")
        cfg = parsed.get("config")
        if template in _OPERATOR_CONFIG_KEYS and isinstance(cfg, dict):
            allowed = _OPERATOR_CONFIG_KEYS[template]
            unexpected = sorted(set(cfg) - allowed)
            if unexpected:
                errors.append(
                    f"Cell {i}: '{template}' config has unexpected key(s) "
                    f"{unexpected} — Designer allows only {sorted(allowed)}"
                )

        # Body (if any) must be valid Python.
        if body.strip():
            try:
                ast.parse(body)
            except SyntaxError as exc:
                errors.append(f"Cell {i}: body is not valid Python: {exc.msg} (line {exc.lineno})")

    # 4. Every input reference must resolve to a defined cell id.
    for i, ref in input_refs:
        if ref not in defined_ids:
            errors.append(f"Cell {i}: input references undefined node id {ref!r}")

    return DesignerValidationResult(
        is_valid=not errors,
        cell_count=len(cells),
        errors=errors,
        warnings=warnings,
    )
