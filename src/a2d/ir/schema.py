"""Columns flowing between tools, from what the Alteryx file saved.

Designer saves each tool's output columns after a run (``<MetaInfo>``; kept on
``IRNode.output_fields``). Many tools don't save them, so a tool's columns are
also derived from its input for tools whose effect on columns is known: Filter,
Sort, Sample, Unique, Browse and Message keep them, Formula and Record ID add
fields, Select drops and renames them. Anything else is unknown (None) rather
than guessed.
"""

from __future__ import annotations

from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    AppendFieldsNode,
    BrowseNode,
    FilterNode,
    FormulaNode,
    IRNode,
    JoinNode,
    RecordIDNode,
    SampleNode,
    SelectNode,
    SortNode,
    SummarizeNode,
    UniqueNode,
    UnsupportedNode,
)

Columns = list[tuple[str, str]]  # (name, type); type is "" when not known

_KEEP_COLUMNS = (FilterNode, SortNode, SampleNode, UniqueNode, BrowseNode)
_KEEP_COLUMNS_TOOLS = {"Message", "Test"}  # unsupported tools that pass rows through unchanged
_MAX_DEPTH = 200


def output_columns(dag: WorkflowDAG, node_id: int, anchor: str = "Output", _depth: int = 0) -> Columns | None:
    """The columns ``node_id`` sends out of ``anchor``, or None if unknown."""
    if _depth > _MAX_DEPTH:
        return None
    try:
        node = dag.get_node(node_id)
    except KeyError:
        return None
    saved = _saved(node, anchor)
    if saved is not None:
        return saved
    if isinstance(node, _KEEP_COLUMNS) or (
        isinstance(node, UnsupportedNode) and node.original_tool_type in _KEEP_COLUMNS_TOOLS
    ):
        return _single_input(dag, node_id, _depth)
    if isinstance(node, FormulaNode):
        cols = _single_input(dag, node_id, _depth)
        if cols is None:
            return None
        out = list(cols)
        names = [n for n, _ in out]
        for f in node.formulas:
            if f.output_field in names:
                continue
            out.append((f.output_field, f.data_type or ""))
            names.append(f.output_field)
        return out
    if isinstance(node, RecordIDNode):
        cols = _single_input(dag, node_id, _depth)
        return None if cols is None else [(node.output_field, node.output_type or ""), *cols]
    if isinstance(node, SelectNode):
        cols = _single_input(dag, node_id, _depth)
        return None if cols is None else _apply_select(node, cols)
    if isinstance(node, SummarizeNode):
        # Group-by and aggregate fields, under their output names. Types change
        # with the aggregation, so only group-by fields keep theirs.
        cols = _single_input(dag, node_id, _depth)
        types = dict(cols or [])
        return [
            (a.output_field_name or a.field_name, types.get(a.field_name, "") if a.action.name == "GROUP_BY" else "")
            for a in node.aggregations
        ]
    if isinstance(node, JoinNode):
        ins = input_columns(dag, node_id, _depth)
        left, right = ins.get("Left"), ins.get("Right")
        if anchor == "Left":
            return left
        if anchor == "Right":
            return right
        if left is None or right is None:
            return None
        return _join_output(node, left, right)
    if isinstance(node, AppendFieldsNode):
        ins = input_columns(dag, node_id, _depth)
        target = ins.get("Targets", ins.get("Target", ins.get("Input")))
        source = ins.get("Source")
        if target is None or source is None:
            return None
        names = {n for n, _ in target}
        if any(n in names for n, _ in source):
            return None  # how Append Fields names a clash isn't confirmed, so don't guess
        return [*target, *source]
    return None


def input_columns(dag: WorkflowDAG, node_id: int, _depth: int = 0) -> dict[str, Columns | None]:
    """Columns arriving on each input anchor of ``node_id`` (anchor -> columns or None)."""
    result: dict[str, Columns | None] = {}
    for pred in dag.get_predecessors(node_id):
        info = dag.get_edge_info(pred.node_id, node_id)
        anchor = info.destination_anchor
        if anchor in result:  # several connections on one anchor (Union): number them
            n = 2
            while f"{anchor}_{n}" in result:
                n += 1
            anchor = f"{anchor}_{n}"
        result[anchor] = output_columns(dag, pred.node_id, info.origin_anchor, _depth + 1)
    return result


def _saved(node: IRNode, anchor: str) -> Columns | None:
    fields = node.output_fields
    if not fields:
        return None
    if anchor in fields:
        return list(fields[anchor])
    # A single-output tool saves one MetaInfo with no connection name ("Output").
    if len(fields) == 1 and anchor in ("Output", "True", "Join", "Unique") and "Output" in fields:
        return list(fields["Output"])
    return None


def _single_input(dag: WorkflowDAG, node_id: int, depth: int) -> Columns | None:
    preds = dag.get_predecessors(node_id)
    if len(preds) != 1:
        return None
    info = dag.get_edge_info(preds[0].node_id, node_id)
    return output_columns(dag, preds[0].node_id, info.origin_anchor, depth + 1)


def _apply_select(node: SelectNode, cols: Columns) -> Columns:
    ops = {op.field_name: op for op in node.field_operations}
    out: Columns = []
    for name, typ in cols:
        op = ops.get(name)
        if op is None:
            if node.select_all_unknown:
                out.append((name, typ))
            continue
        if not op.selected:
            continue
        out.append((op.rename_to or name, op.new_type or typ))
    return out


def _join_output(node: JoinNode, left: Columns, right: Columns) -> Columns:
    """A Join's J output: right-side names also on the left become Right_<name>,
    then the Join's Select settings apply (see generators/join_code.py)."""
    left_names = {n for n, _ in left}
    cols = [*left, *[(f"Right_{n}" if n in left_names else n, t) for n, t in right]]
    ops = {op.field_name: op for op in node.select_left + node.select_right}
    out: Columns = []
    for name, typ in cols:
        op = ops.get(name)
        if op is None:
            if node.keep_unlisted:
                out.append((name, typ))
        elif op.selected:
            out.append((op.rename_to or name, typ))
    return out


def describe(cols: Columns | None, limit: int = 60) -> str:
    """Columns as one line for a prompt: ``a (String), b (Int64), ...``."""
    if cols is None:
        return "not known"
    if not cols:
        return "none"
    shown = [f"{n} ({t})" if t else n for n, t in cols[:limit]]
    more = f", ... ({len(cols) - limit} more)" if len(cols) > limit else ""
    return ", ".join(shown) + more
