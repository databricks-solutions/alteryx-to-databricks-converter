"""Optional Spark execution backend for equivalence verification.

Executes the IR DAG through PySpark DataFrame operations — an independent third
implementation (alongside pandas reference and the generated code) whose results
can be cross-checked with the parity engine.

Spark requires a JVM. On a laptop without Java this backend is unavailable, so
:func:`spark_available` is checked first and :meth:`SparkBackend.execute`
returns a result flagged ``available=False`` rather than crashing. On Databricks
or CI (where Java exists) it runs for real.

The op set mirrors :class:`a2d.verification.reference.ReferenceExecutor` exactly,
so pandas-vs-Spark agreement is a meaningful equivalence signal.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import reduce
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    import pandas as pd


def _resolve_java() -> str | None:
    """Return a path to a java executable, preferring ``$JAVA_HOME/bin/java``."""
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidate = os.path.join(java_home, "bin", "java")
        if os.path.isfile(candidate):
            return candidate
    return shutil.which("java")


def spark_available() -> tuple[bool, str]:
    """Return ``(available, reason)``. Requires pyspark AND a *working* JVM.

    Note: on macOS ``java`` is often a stub on PATH that errors unless a real
    JRE is installed, so we actually run ``java -version`` rather than trusting
    ``shutil.which`` alone.
    """
    try:
        import pyspark  # noqa: F401
    except ImportError:
        return False, "pyspark is not installed (pip install 'alteryx2databricks[verify]')"

    java = _resolve_java()
    if not java:
        return False, "no Java runtime found (Spark requires a JVM; run on Databricks/CI or install Java)"
    try:
        proc = subprocess.run(
            [java, "-version"], capture_output=True, timeout=15, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Java runtime not usable: {exc}"
    if proc.returncode != 0:
        return False, "Java runtime present but not functional (install a real JDK/JRE)"
    return True, "available"


@dataclass
class SparkResult:
    """Outcome of a Spark execution over a DAG."""

    available: bool
    reason: str = ""
    outputs: dict[int, pd.DataFrame] = field(default_factory=dict)  # node_id -> pandas
    skipped: list[tuple[int, str]] = field(default_factory=list)
    sink_node_ids: list[int] = field(default_factory=list)


class UnsupportedSparkOperationError(Exception):
    """Raised when the Spark backend has no implementation for a node."""


class SparkBackend:
    """Execute an IR DAG through PySpark over supplied source data."""

    def __init__(self, source_data: dict[str | int, pd.DataFrame] | None = None) -> None:
        self.source_data = source_data or {}
        self._spark = None

    def _session(self):
        if self._spark is None:
            from pyspark.sql import SparkSession

            self._spark = (
                SparkSession.builder.master("local[1]")
                .appName("a2d-verify")
                .config("spark.ui.enabled", "false")
                .config("spark.sql.shuffle.partitions", "1")
                .getOrCreate()
            )
        return self._spark

    def execute(self, dag: WorkflowDAG) -> SparkResult:
        ok, reason = spark_available()
        if not ok:
            return SparkResult(available=False, reason=reason)

        result = SparkResult(available=True)
        spark_frames: dict[int, Any] = {}
        try:
            for node in dag.topological_order():
                try:
                    sdf = self._eval_node(node, dag, spark_frames)
                except UnsupportedSparkOperationError as exc:
                    result.skipped.append((node.node_id, str(exc)))
                    inputs = self._input_frames(node, dag, spark_frames)
                    if len(inputs) == 1:
                        spark_frames[node.node_id] = next(iter(inputs.values()))
                    continue
                if sdf is not None:
                    spark_frames[node.node_id] = sdf
            # Materialize every node result to pandas for the parity engine.
            for node_id, sdf in spark_frames.items():
                result.outputs[node_id] = sdf.toPandas()
            result.sink_node_ids = [n.node_id for n in dag.get_sink_nodes()]
        finally:
            if self._spark is not None:
                self._spark.stop()
                self._spark = None
        return result

    # -- Input resolution (mirrors ReferenceExecutor) --

    def _input_frames(self, node: IRNode, dag: WorkflowDAG, frames: dict[int, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for pred in dag.get_predecessors(node.node_id):
            if pred.node_id not in frames:
                continue
            edge = dag.get_edge_info(pred.node_id, node.node_id)
            out[edge.destination_anchor] = self._branch(pred, edge, frames)
        return out

    def _all_input_frames(self, node: IRNode, dag: WorkflowDAG, frames: dict[int, Any]) -> list[Any]:
        """Every upstream frame (one per edge), preserving inputs that share an anchor."""
        out: list[Any] = []
        for pred in dag.get_predecessors(node.node_id):
            if pred.node_id not in frames:
                continue
            edge = dag.get_edge_info(pred.node_id, node.node_id)
            out.append(self._branch(pred, edge, frames))
        return out

    @staticmethod
    def _branch(pred: IRNode, edge, frames: dict[int, Any]) -> Any:
        base = frames[pred.node_id]
        if isinstance(pred, FilterNode) and edge.origin_anchor == "False":
            return getattr(pred, "_spark_false_df", base)
        return base

    def _single_input(self, node: IRNode, dag: WorkflowDAG, frames: dict[int, Any]) -> Any:
        inputs = self._input_frames(node, dag, frames)
        if not inputs:
            raise UnsupportedSparkOperationError(f"Node {node.node_id} has no available input")
        return inputs.get("Input", next(iter(inputs.values())))

    # -- Node evaluation --

    def _eval_node(self, node: IRNode, dag: WorkflowDAG, frames: dict[int, Any]) -> Any:
        from pyspark.sql import functions as F

        if isinstance(node, ReadNode):
            return self._read(node)
        if isinstance(node, LiteralDataNode):
            return self._literal(node)
        if isinstance(node, (AutoFieldNode | BrowseNode | WriteNode)):
            return self._single_input(node, dag, frames)
        if isinstance(node, FilterNode):
            df = self._single_input(node, dag, frames)
            if not node.expression or not node.expression.strip():
                raise UnsupportedSparkOperationError(f"Filter node {node.node_id} has no expression")
            from a2d.expressions.base_translator import BaseTranslationError
            from a2d.expressions.sql_translator import SparkSQLTranslator

            try:
                cond = SparkSQLTranslator().translate_string(node.expression)
            except BaseTranslationError as exc:
                raise UnsupportedSparkOperationError(f"Filter expr not translatable: {exc}") from exc
            node._spark_false_df = df.filter(f"NOT ({cond})")  # type: ignore[attr-defined]
            return df.filter(cond)
        if isinstance(node, SelectNode):
            return self._select(node, self._single_input(node, dag, frames))
        if isinstance(node, FormulaNode):
            from a2d.expressions.base_translator import BaseTranslationError
            from a2d.expressions.sql_translator import SparkSQLTranslator

            df = self._single_input(node, dag, frames)
            translator = SparkSQLTranslator()
            for f in node.formulas:
                try:
                    expr = translator.translate_string(f.expression)
                except BaseTranslationError as exc:
                    raise UnsupportedSparkOperationError(f"Formula expr not translatable: {exc}") from exc
                df = df.withColumn(f.output_field, F.expr(expr))
            return df
        if isinstance(node, SortNode):
            df = self._single_input(node, dag, frames)
            if not node.sort_fields:
                return df
            cols = [
                F.col(sf.field_name).asc() if sf.ascending else F.col(sf.field_name).desc()
                for sf in node.sort_fields
            ]
            return df.orderBy(*cols)
        if isinstance(node, SampleNode):
            df = self._single_input(node, dag, frames)
            if node.n_records is not None and (node.sample_method or "first") == "first":
                return df.limit(node.n_records)
            raise UnsupportedSparkOperationError(f"Sample node {node.node_id}: unsupported method")
        if isinstance(node, RecordIDNode):
            from pyspark.sql.window import Window

            df = self._single_input(node, dag, frames)
            w = Window.orderBy(F.monotonically_increasing_id())
            return df.withColumn(
                node.output_field, (F.row_number().over(w) + (node.starting_value - 1))
            )
        if isinstance(node, CountRecordsNode):
            df = self._single_input(node, dag, frames)
            return df.agg(F.count(F.lit(1)).alias(node.output_field))
        if isinstance(node, UnionNode):
            inputs = self._all_input_frames(node, dag, frames)
            if not inputs:
                raise UnsupportedSparkOperationError(f"Union node {node.node_id} has no inputs")
            return reduce(lambda a, b: a.unionByName(b, allowMissingColumns=True), inputs)
        if isinstance(node, JoinNode):
            return self._join(node, dag, frames)
        if isinstance(node, SummarizeNode):
            return self._summarize(node, self._single_input(node, dag, frames))
        raise UnsupportedSparkOperationError(f"No Spark implementation for {type(node).__name__}")

    # -- Operators --

    def _read(self, node: ReadNode) -> Any:
        for key in (node.node_id, node.table_name, node.file_path):
            if key and key in self.source_data:
                return self._session().createDataFrame(self.source_data[key])
        raise UnsupportedSparkOperationError(f"No source data for ReadNode {node.node_id}")

    def _literal(self, node: LiteralDataNode) -> Any:
        import pandas as pd

        if node.node_id in self.source_data:
            return self._session().createDataFrame(self.source_data[node.node_id])
        if not node.field_names:
            raise UnsupportedSparkOperationError(f"LiteralData node {node.node_id} has no fields")
        from a2d.verification.reference import _coerce_numeric

        cols = node.field_names
        rows = [row[: len(cols)] for row in node.data_rows]
        pdf = _coerce_numeric(pd.DataFrame(rows, columns=cols))
        return self._session().createDataFrame(pdf)

    def _select(self, node: SelectNode, df: Any) -> Any:
        drops = [
            op.field_name for op in node.field_operations
            if not op.selected or op.action == FieldAction.DESELECT
        ]
        if drops:
            df = df.drop(*[c for c in drops if c in df.columns])
        for op in node.field_operations:
            if op.action == FieldAction.RENAME and op.rename_to:
                df = df.withColumnRenamed(op.field_name, op.rename_to)
        return df

    def _join(self, node: JoinNode, dag: WorkflowDAG, frames: dict[int, Any]) -> Any:
        inputs = self._input_frames(node, dag, frames)
        left = inputs.get("Left", inputs.get("Input"))
        right = inputs.get("Right")
        if left is None or right is None:
            raise UnsupportedSparkOperationError(f"Join node {node.node_id} missing input")
        if not node.join_keys:
            raise UnsupportedSparkOperationError(f"Join node {node.node_id} has no keys")
        how = {"inner": "inner", "left": "left", "right": "right", "full": "outer"}.get(
            (node.join_type or "inner").lower(), "inner"
        )
        from pyspark.sql import functions as F

        cond = [F.col(f"l.{jk.left_field}") == F.col(f"r.{jk.right_field}") for jk in node.join_keys]
        combined = cond[0]
        for c in cond[1:]:
            combined = combined & c
        return left.alias("l").join(right.alias("r"), combined, how)

    def _summarize(self, node: SummarizeNode, df: Any) -> Any:
        from pyspark.sql import functions as F

        group_cols = [a.field_name for a in node.aggregations if a.action == AggAction.GROUP_BY]
        agg_specs = [a for a in node.aggregations if a.action != AggAction.GROUP_BY]
        func_map: dict[AggAction, Callable[[str], Any]] = {
            AggAction.SUM: F.sum,
            AggAction.COUNT: F.count,
            AggAction.MIN: F.min,
            AggAction.MAX: F.max,
            AggAction.AVG: F.avg,
            AggAction.FIRST: F.first,
            AggAction.LAST: F.last,
            AggAction.COUNT_DISTINCT: F.countDistinct,
        }

        def alias(a) -> str:
            return a.output_field_name or f"{a.action.value}_{a.field_name}"

        if not agg_specs:
            return df.select(*group_cols).distinct() if group_cols else df.agg(F.count(F.lit(1)).alias("count"))
        for a in agg_specs:
            if a.action not in func_map:
                raise UnsupportedSparkOperationError(f"Summarize action {a.action.value} unsupported")
        agg_exprs = [func_map[a.action](a.field_name).alias(alias(a)) for a in agg_specs]
        if group_cols:
            return df.groupBy(*group_cols).agg(*agg_exprs)
        return df.agg(*agg_exprs)
