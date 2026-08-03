"""Turn declarative candidate proposals into real IR sub-DAGs.

A :class:`ConversionCandidate` describes its nodes as ``ProposedNode`` records
with a ``kind`` (IR class name) and JSON-primitive ``params``. This module
instantiates them through a strict **allow-list** of supported IR node types —
a model can never name an arbitrary class or inject code, only fill in the
parameters of a known, safe transformation node.
"""

from __future__ import annotations

from collections.abc import Callable

from a2d.ir.nodes import (
    FieldAction,
    FieldOperation,
    FilterNode,
    FormulaField,
    FormulaNode,
    IRNode,
    SampleNode,
    SelectNode,
    SortField,
    SortNode,
)


class CandidateBuildError(Exception):
    """Raised when a candidate references an unknown kind or malformed params."""


def _build_select(node_id: int, params: dict) -> SelectNode:
    ops_raw = params.get("field_operations", [])
    field_operations = []
    for op in ops_raw:
        if not isinstance(op, dict):
            raise CandidateBuildError("SelectNode field_operations entries must be objects")
        action = FieldAction(str(op.get("action", "select")))
        field_operations.append(
            FieldOperation(
                field_name=str(op["field_name"]),
                action=action,
                rename_to=op.get("rename_to"),
                selected=bool(op.get("selected", True)),
            )
        )
    return SelectNode(
        node_id=node_id,
        field_operations=field_operations,
        select_all_unknown=bool(params.get("select_all_unknown", True)),
    )


def _build_filter(node_id: int, params: dict) -> FilterNode:
    return FilterNode(
        node_id=node_id,
        expression=str(params.get("expression", "")),
        mode=str(params.get("mode", "simple")),
    )


def _build_formula(node_id: int, params: dict) -> FormulaNode:
    formulas_raw = params.get("formulas", [])
    formulas = []
    for f in formulas_raw:
        if not isinstance(f, dict):
            raise CandidateBuildError("FormulaNode formulas entries must be objects")
        formulas.append(
            FormulaField(
                output_field=str(f["output_field"]),
                expression=str(f["expression"]),
                data_type=str(f.get("data_type", "")),
            )
        )
    return FormulaNode(node_id=node_id, formulas=formulas)


def _build_sort(node_id: int, params: dict) -> SortNode:
    fields_raw = params.get("sort_fields", [])
    sort_fields = []
    for s in fields_raw:
        if not isinstance(s, dict):
            raise CandidateBuildError("SortNode sort_fields entries must be objects")
        sort_fields.append(SortField(field_name=str(s["field_name"]), ascending=bool(s.get("ascending", True))))
    return SortNode(node_id=node_id, sort_fields=sort_fields)


def _build_sample(node_id: int, params: dict) -> SampleNode:
    n = params.get("n_records")
    return SampleNode(
        node_id=node_id,
        sample_method=str(params.get("sample_method", "first")),
        n_records=int(n) if n is not None else None,
    )


# Allow-list: only these IR node kinds may appear in a candidate. Each builder
# validates and coerces the JSON params into a real IR node instance.
_BUILDERS: dict[str, Callable[[int, dict], IRNode]] = {
    "SelectNode": _build_select,
    "FilterNode": _build_filter,
    "FormulaNode": _build_formula,
    "SortNode": _build_sort,
    "SampleNode": _build_sample,
}

ALLOWED_KINDS = frozenset(_BUILDERS)


def build_node(kind: str, node_id: int, params: dict) -> IRNode:
    """Instantiate one allow-listed IR node from a candidate's declaration."""
    builder = _BUILDERS.get(kind)
    if builder is None:
        raise CandidateBuildError(f"kind {kind!r} is not in the allowed set {sorted(ALLOWED_KINDS)}")
    try:
        node = builder(node_id, params)
    except (KeyError, ValueError, TypeError) as exc:
        raise CandidateBuildError(f"malformed params for {kind}: {exc}") from exc
    node.original_tool_type = kind.replace("Node", "")
    node.conversion_method = "llm-assisted"
    return node
