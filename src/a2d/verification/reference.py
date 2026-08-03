"""Pandas reference executor — an independent implementation of IR semantics.

Walks a :class:`~a2d.ir.graph.WorkflowDAG` and evaluates each node against
pandas DataFrames, producing a result per node. This is deliberately a *second*
implementation of the workflow semantics (separate from the PySpark/SQL
generators), so agreement between the two is genuine equivalence signal.

Only the common "native" operators are implemented. Unsupported nodes raise
:class:`UnsupportedOperationError`, and :meth:`ReferenceExecutor.execute` records
them as skipped rather than guessing — a verify run over a workflow with
unsupported nodes reports *partial* coverage, never a false pass.

Input data is supplied per source node via ``source_data`` (keyed by node_id or
by table/file identifier); this keeps the executor pure and testable without
touching the filesystem or a warehouse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    AggAction,
    AutoFieldNode,
    BrowseNode,
    CountRecordsNode,
    FieldAction,
    FilterNode,
    FormulaNode,
    IRNode,
    JoinNode,
    LiteralDataNode,
    ReadNode,
    RecordIDNode,
    SampleNode,
    SelectNode,
    SortNode,
    SummarizeNode,
    UnionNode,
    WriteNode,
)
from a2d.verification.expr_eval import UnsupportedExpressionError, evaluate_expression

if TYPE_CHECKING:
    import pandas as pd


class UnsupportedOperationError(Exception):
    """Raised when the reference executor has no implementation for a node."""


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Best-effort per-column numeric coercion so inline "100" compares as a number.

    A column is converted only if *every* non-null value parses as numeric,
    matching how a warehouse would type an all-numeric text column.
    """
    import pandas as pd

    for c in df.columns:
        converted = pd.to_numeric(df[c], errors="coerce")
        # Only adopt the numeric version if nothing that was non-null became NaN.
        original_nonnull = df[c].notna()
        if bool((converted.notna() | ~original_nonnull).all()):
            df[c] = converted
    return df


@dataclass
class ReferenceResult:
    """Outcome of a reference execution over a DAG."""

    outputs: dict[int, pd.DataFrame] = field(default_factory=dict)  # node_id -> result
    skipped: list[tuple[int, str]] = field(default_factory=list)  # (node_id, reason)
    sink_node_ids: list[int] = field(default_factory=list)

    @property
    def fully_supported(self) -> bool:
        return not self.skipped


class ReferenceExecutor:
    """Execute an IR DAG in pandas over supplied source data."""

    def __init__(self, source_data: dict[str | int, pd.DataFrame] | None = None) -> None:
        # Keys may be node_id (int) or a source identifier (table name / file path).
        self.source_data = source_data or {}

    def execute(self, dag: WorkflowDAG) -> ReferenceResult:
        result = ReferenceResult()
        for node in dag.topological_order():
            try:
                df = self._eval_node(node, dag, result)
            except (UnsupportedOperationError, UnsupportedExpressionError) as exc:
                result.skipped.append((node.node_id, str(exc)))
                # Best-effort passthrough so downstream nodes can still run when
                # a non-transforming node (e.g. Browse) is unsupported.
                inputs = self._input_frames(node, dag, result)
                if len(inputs) == 1:
                    result.outputs[node.node_id] = next(iter(inputs.values()))
                continue
            if df is not None:
                result.outputs[node.node_id] = df

        result.sink_node_ids = [n.node_id for n in dag.get_sink_nodes()]
        return result

    # -- Input resolution --

    def _input_frames(self, node: IRNode, dag: WorkflowDAG, result: ReferenceResult) -> dict[str, pd.DataFrame]:
        """Map destination anchor -> upstream result DataFrame.

        Note: when multiple upstreams share a destination anchor (e.g. several
        inputs into a Union's default anchor) they collide here — use
        :meth:`_all_input_frames` for many-input operators like Union.
        """
        frames: dict[str, pd.DataFrame] = {}
        for pred in dag.get_predecessors(node.node_id):
            if pred.node_id not in result.outputs:
                continue
            edge = dag.get_edge_info(pred.node_id, node.node_id)
            frames[edge.destination_anchor] = self._branch_frame(pred, edge, result)
        return frames

    def _all_input_frames(self, node: IRNode, dag: WorkflowDAG, result: ReferenceResult) -> list[pd.DataFrame]:
        """Return every upstream frame (one per incoming edge), order-stable.

        Unlike :meth:`_input_frames`, this does not key by anchor, so multiple
        inputs sharing an anchor are all preserved (needed for Union).
        """
        frames: list[pd.DataFrame] = []
        for pred in dag.get_predecessors(node.node_id):
            if pred.node_id not in result.outputs:
                continue
            edge = dag.get_edge_info(pred.node_id, node.node_id)
            frames.append(self._branch_frame(pred, edge, result))
        return frames

    def _branch_frame(self, pred: IRNode, edge, result: ReferenceResult) -> pd.DataFrame:
        """Apply filter fan-out: the 'False' anchor yields the excluded rows.

        The main stored output of a FilterNode is its True (kept) rows; the
        excluded rows are stashed on the node during evaluation.
        """
        base = result.outputs[pred.node_id]
        if isinstance(pred, FilterNode) and edge.origin_anchor == "False":
            false_rows = getattr(pred, "_ref_false_rows", None)
            if false_rows is not None:
                return false_rows
        return base

    def _single_input(self, node: IRNode, dag: WorkflowDAG, result: ReferenceResult) -> pd.DataFrame:
        frames = self._input_frames(node, dag, result)
        if not frames:
            raise UnsupportedOperationError(f"Node {node.node_id} has no available input")
        if "Input" in frames:
            return frames["Input"]
        return next(iter(frames.values()))

    # -- Node evaluation --

    def _eval_node(self, node: IRNode, dag: WorkflowDAG, result: ReferenceResult) -> pd.DataFrame | None:
        import pandas as pd

        if isinstance(node, ReadNode):
            return self._read(node)

        if isinstance(node, LiteralDataNode):
            return self._literal(node)

        if isinstance(node, (AutoFieldNode | BrowseNode)):
            return self._single_input(node, dag, result)

        if isinstance(node, WriteNode):
            return self._single_input(node, dag, result)

        if isinstance(node, FilterNode):
            df = self._single_input(node, dag, result)
            if not node.expression or not node.expression.strip():
                raise UnsupportedOperationError(f"Filter node {node.node_id} has no expression")
            mask = evaluate_expression(node.expression, df)
            mask = mask.fillna(False).astype(bool)
            # Store the False branch so a downstream 'False' anchor can pick it up.
            node._ref_false_rows = df[~mask].reset_index(drop=True)  # type: ignore[attr-defined]
            return df[mask].reset_index(drop=True)

        if isinstance(node, SelectNode):
            return self._select(node, self._single_input(node, dag, result))

        if isinstance(node, FormulaNode):
            df = self._single_input(node, dag, result).copy()
            for f in node.formulas:
                df[f.output_field] = evaluate_expression(f.expression, df)
            return df

        if isinstance(node, SortNode):
            df = self._single_input(node, dag, result)
            if not node.sort_fields:
                return df
            by = [sf.field_name for sf in node.sort_fields]
            asc = [sf.ascending for sf in node.sort_fields]
            return df.sort_values(by=by, ascending=asc, kind="stable").reset_index(drop=True)

        if isinstance(node, SampleNode):
            return self._sample(node, self._single_input(node, dag, result))

        if isinstance(node, RecordIDNode):
            df = self._single_input(node, dag, result).copy()
            df.insert(0, node.output_field, range(node.starting_value, node.starting_value + len(df)))
            return df

        if isinstance(node, CountRecordsNode):
            df = self._single_input(node, dag, result)
            return pd.DataFrame({node.output_field: [len(df)]})

        if isinstance(node, UnionNode):
            frames = self._all_input_frames(node, dag, result)
            if not frames:
                raise UnsupportedOperationError(f"Union node {node.node_id} has no inputs")
            return pd.concat(frames, ignore_index=True, sort=False)

        if isinstance(node, JoinNode):
            return self._join(node, dag, result)

        if isinstance(node, SummarizeNode):
            return self._summarize(node, self._single_input(node, dag, result))

        raise UnsupportedOperationError(f"No reference implementation for {type(node).__name__}")

    # -- Operator implementations --

    def _read(self, node: ReadNode) -> pd.DataFrame:
        for key in (node.node_id, node.table_name, node.file_path):
            if key and key in self.source_data:
                return self.source_data[key].copy()
        raise UnsupportedOperationError(
            f"No source data provided for ReadNode {node.node_id} (table={node.table_name!r}, path={node.file_path!r})"
        )

    def _literal(self, node: LiteralDataNode) -> pd.DataFrame:
        import pandas as pd

        # Prefer caller-supplied override (keyed by node id) if present, else use
        # the data embedded in the workflow's TextInput / literal node.
        if node.node_id in self.source_data:
            return self.source_data[node.node_id].copy()
        if not node.field_names:
            raise UnsupportedOperationError(f"LiteralData node {node.node_id} has no fields")
        cols = node.field_names
        rows = [row[: len(cols)] for row in node.data_rows]
        df = pd.DataFrame(rows, columns=cols)
        return _coerce_numeric(df)

    def _select(self, node: SelectNode, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        drops: list[str] = []
        renames: dict[str, str] = {}
        for op in node.field_operations:
            if not op.selected or op.action == FieldAction.DESELECT:
                drops.append(op.field_name)
            elif op.action == FieldAction.RENAME and op.rename_to:
                renames[op.field_name] = op.rename_to
        if drops:
            result = result.drop(columns=[c for c in drops if c in result.columns])
        if renames:
            result = result.rename(columns=renames)
        return result

    def _sample(self, node: SampleNode, df: pd.DataFrame) -> pd.DataFrame:
        method = node.sample_method or "first"
        if node.n_records is not None:
            if method == "first":
                return df.head(node.n_records).reset_index(drop=True)
            if method == "last":
                return df.tail(node.n_records).reset_index(drop=True)
        if node.percentage is not None:
            n = int(len(df) * node.percentage / 100.0)
            return df.head(n).reset_index(drop=True)
        raise UnsupportedOperationError(f"Sample node {node.node_id}: unsupported method {method!r}")

    def _join(self, node: JoinNode, dag: WorkflowDAG, result: ReferenceResult) -> pd.DataFrame:
        frames = self._input_frames(node, dag, result)
        left = frames.get("Left", frames.get("Input"))
        right = frames.get("Right")
        if left is None or right is None:
            raise UnsupportedOperationError(f"Join node {node.node_id} missing left/right input")
        if not node.join_keys:
            raise UnsupportedOperationError(f"Join node {node.node_id} has no keys")
        how = {"inner": "inner", "left": "left", "right": "right", "full": "outer"}.get(
            (node.join_type or "inner").lower(), "inner"
        )
        left_on = [jk.left_field for jk in node.join_keys]
        right_on = [jk.right_field for jk in node.join_keys]
        return left.merge(right, left_on=left_on, right_on=right_on, how=how, suffixes=("", "_right"))

    def _summarize(self, node: SummarizeNode, df: pd.DataFrame) -> pd.DataFrame:
        import pandas as pd

        group_cols = [a.field_name for a in node.aggregations if a.action == AggAction.GROUP_BY]
        agg_specs = [a for a in node.aggregations if a.action != AggAction.GROUP_BY]

        pandas_func = {
            AggAction.SUM: "sum",
            AggAction.COUNT: "count",
            AggAction.MIN: "min",
            AggAction.MAX: "max",
            AggAction.AVG: "mean",
            AggAction.FIRST: "first",
            AggAction.LAST: "last",
            AggAction.COUNT_DISTINCT: "nunique",
        }

        def alias(a) -> str:
            return a.output_field_name or f"{a.action.value}_{a.field_name}"

        if not agg_specs:
            # Pure group-by → distinct groups (or a single count if no groups).
            if group_cols:
                return df[group_cols].drop_duplicates().reset_index(drop=True)
            return pd.DataFrame({"count": [len(df)]})

        for a in agg_specs:
            if a.action not in pandas_func:
                raise UnsupportedOperationError(f"Summarize action {a.action.value} not supported in reference")

        # Detect alias collisions rather than silently overwriting a column
        # (two aggregations resolving to the same output name).
        aliases = [alias(a) for a in agg_specs]
        dupes = {n for n in aliases if aliases.count(n) > 1}
        if dupes:
            raise UnsupportedOperationError(
                f"Summarize has colliding output column name(s): {sorted(dupes)} — "
                "give the aggregations distinct output names"
            )

        if group_cols:
            grouped = df.groupby(group_cols, dropna=False, sort=True)
            out_cols = {}
            for a in agg_specs:
                out_cols[alias(a)] = grouped[a.field_name].agg(pandas_func[a.action])
            out = pd.DataFrame(out_cols).reset_index()
            return out
        # No group-by: single-row aggregate.
        row = {alias(a): [getattr(df[a.field_name], pandas_func[a.action])()] for a in agg_specs}
        return pd.DataFrame(row)
