"""Lakeflow Designer (``.designer.ipynb``) generator.

Emits a **native Lakeflow Designer visual-ETL file** — a Jupyter notebook where
each IR node becomes one operator *cell* that Designer rehydrates into a
draggable node on its drag-and-drop canvas. This is distinct from the
``lakeflow`` format, which emits Lakeflow Declarative Pipelines (LDP) SQL text.

The file contract (documented in ``docs/lakeflow-designer-generator-design.md``):

* A ``.designer.ipynb`` is a standard Jupyter notebook (``nbformat: 4``). Each
  operator is one **code cell** whose ``source`` begins with a triple-quoted
  **YAML docstring** ("annotation") that Designer parses to build the canvas.
* The annotation carries ``id``, ``template``, ``templateVersion``, ``name``,
  ``position:{x,y}``, ``description``, ``config`` and ``input[]`` wiring.
* Notebook- and cell-level Databricks metadata keys are **required** or the DAG
  fails to render on import; each cell needs a unique ``nuid``.
* ``previewCodeHash`` / ``description.hash`` are Designer-internal content
  hashes whose algorithm is not public. They are emitted **empty** — Designer
  recomputes them on open (matches the ``brickify`` field-eng assembler).

Determinism: unlike the existing LLM-based Alteryx→Designer tools, this
generator is a pure function of the IR DAG (same input → same output). Clean
Alteryx tools map to **native** Designer operators; everything else falls back
to a ``sql`` or ``python`` operator cell (reusing the tested
:class:`~a2d.generators.sql.SQLGenerator` bodies), mirroring the field-eng
operator-mapping playbook.
"""

from __future__ import annotations

import json
import logging
import re
import uuid

from a2d.config import ConversionConfig
from a2d.generators.base import CodeGenerator, GeneratedFile, GeneratedOutput
from a2d.generators.sql import SQLGenerator, _cte_name
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    AggAction,
    AutoFieldNode,
    BrowseNode,
    CommentNode,
    CountRecordsNode,
    CrossTabNode,
    DataCleansingNode,
    FieldAction,
    FilterNode,
    FormulaNode,
    IRNode,
    JoinNode,
    PythonToolNode,
    ReadNode,
    SampleNode,
    SelectNode,
    SortNode,
    SummarizeNode,
    UnionNode,
    UnsupportedNode,
    WriteNode,
)

logger = logging.getLogger("a2d.generators.designer")

# ── Operator template version pins ──────────────────────────────────────────
# Exactly one (prod-latest) version per operator, matching the field-eng
# ``brickify`` catalog. Version bumps that change *ports* are the hazard
# (filter@2 adds ``excluded_data``; combine@2 uses a variadic ``data`` port),
# so these are pinned deliberately. Hand-maintained until Databricks ships a
# served catalog — see docs/lakeflow-designer-generator-design.md §3.4.
OPERATOR_VERSIONS: dict[str, str] = {
    "source": "2.0.0",
    "output": "1.0.0",
    "transform": "2.0.0",
    "ai_function": "3.0.0",
    "filter": "2.0.0",
    "sort": "1.0.0",
    "limit": "1.0.0",
    "aggregate": "2.0.0",
    "prepare": "1.0.0",
    "combine": "2.0.0",
    "join": "1.0.0",
    "pivot": "1.0.0",
    "python": "1.0.0",
    "sql": "1.0.0",
    "markdown": "1.0.0",
}

# Canvas layout stepping (Designer convention): tiers left→right, lanes top→bottom.
_X_STEP = 260
_Y_STEP = 145

# YAML scalars containing any of these characters (or leading/trailing space,
# or that look like booleans/null) must be double-quoted, else Designer's YAML
# parser mis-reads the annotation and silently drops the cell from the graph.
_QUOTE_TRIGGERS = re.compile(r"""[":#{}\[\],&*!|>%@`]|^\s|\s$""")
_YAML_BOOLISH = frozenset({"true", "false", "null", "yes", "no", "~", ""})


def _designer_id(node: IRNode) -> str:
    """Stable, unique cell id derived from the IR node (reuses SQL naming)."""
    return _cte_name(node)


class DesignerCell:
    """One Lakeflow Designer operator cell (annotation + Python body)."""

    def __init__(
        self,
        *,
        cell_id: str,
        template: str,
        name: str,
        position: tuple[int, int],
        config: dict | None = None,
        inputs: list[dict] | None = None,
        description: str = "",
        body: str = "",
    ) -> None:
        self.cell_id = cell_id
        self.template = template
        self.name = name
        self.position = position
        self.config = config or {}
        self.inputs = inputs or []
        self.description = description
        self.body = body


class DesignerGenerator(CodeGenerator):
    """Generate a native Lakeflow Designer ``.designer.ipynb`` visual-ETL file."""

    # Pure passthrough types: no operator cell, forward the predecessor's id.
    _PASSTHROUGH_TYPES = (AutoFieldNode, BrowseNode)
    # Node groups routed to a single operator builder (tuple form for isinstance).
    _AGGREGATE_TYPES = (SummarizeNode, CountRecordsNode)
    _TRANSFORM_TYPES = (SelectNode, FormulaNode, DataCleansingNode)

    def __init__(self, config: ConversionConfig) -> None:
        super().__init__(config)
        # Reuse the tested SQL generator for fallback (sql/python) operator bodies.
        self._sql = SQLGenerator(config)

    # ── Entry point ─────────────────────────────────────────────────────────

    def generate(self, dag: WorkflowDAG, workflow_name: str = "workflow") -> GeneratedOutput:
        ordered = dag.topological_order()
        warnings: list[str] = []
        id_map: dict[int, str] = {}  # node_id -> designer cell id (or forwarded id)
        cells: list[DesignerCell] = []
        tiers = self._compute_tiers(dag, ordered)
        lane_counter: dict[int, int] = {}

        node_count = 0
        native_count = 0
        unsupported_count = 0

        for node in ordered:
            if isinstance(node, CommentNode):
                cell = self._markdown_cell(node, self._position(node, tiers, lane_counter))
                cells.append(cell)
                id_map[node.node_id] = cell.cell_id
                node_count += 1
                continue

            if isinstance(node, self._PASSTHROUGH_TYPES):
                inputs = self._resolve_inputs(node.node_id, dag, id_map)
                if inputs:
                    # Forward the single upstream id so downstream wiring skips this node.
                    id_map[node.node_id] = inputs[0]["node"]
                    node_count += 1
                    continue

            cell, step_warnings, is_native = self._build_cell(node, dag, id_map, tiers, lane_counter)
            warnings.extend(step_warnings)
            cells.append(cell)
            id_map[node.node_id] = cell.cell_id
            node_count += 1
            if is_native:
                native_count += 1
            if isinstance(node, UnsupportedNode):
                unsupported_count += 1

        self.metadata["stats"] = {
            "total_nodes": node_count,
            "supported_nodes": node_count - unsupported_count,
            "unsupported_nodes": unsupported_count,
            "warnings": len(warnings),
        }

        notebook_json = self._assemble_notebook(cells, workflow_name)

        files = [
            GeneratedFile(
                filename=f"{workflow_name}.designer.ipynb",
                content=notebook_json,
                file_type="ipynb",
            )
        ]

        stats = {
            "total_nodes": node_count,
            "supported_nodes": node_count - unsupported_count,
            "unsupported_nodes": unsupported_count,
            "native_operators": native_count,
            "total_cells": len(cells),
            "warnings": len(warnings),
        }
        return GeneratedOutput(files=files, warnings=warnings, stats=stats)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _compute_tiers(self, dag: WorkflowDAG, ordered: list[IRNode]) -> dict[int, int]:
        """Longest-path depth per node → x tier. Deterministic from topo order."""
        tiers: dict[int, int] = {}
        for node in ordered:
            preds = dag.get_predecessors(node.node_id)
            tiers[node.node_id] = 0 if not preds else 1 + max(tiers.get(p.node_id, 0) for p in preds)
        return tiers

    def _position(self, node: IRNode, tiers: dict[int, int], lane_counter: dict[int, int]) -> tuple[int, int]:
        tier = tiers.get(node.node_id, 0)
        lane = lane_counter.get(tier, 0)
        lane_counter[tier] = lane + 1
        return (tier * _X_STEP, lane * _Y_STEP)

    # ── Wiring ──────────────────────────────────────────────────────────────

    def _resolve_inputs(
        self,
        node_id: int,
        dag: WorkflowDAG,
        id_map: dict[int, str],
        *,
        port_for_anchor: dict[str, str] | None = None,
    ) -> list[dict]:
        """Build the ``input[]`` list: {node, input_port, output_port} per edge.

        ``port_for_anchor`` maps this node's *destination* anchor (e.g. "Left")
        to the Designer input-port name ("left"); defaults to "data".
        """
        result: list[dict] = []
        for pred in dag.get_predecessors(node_id):
            upstream_id = id_map.get(pred.node_id, _cte_name(pred))
            edge = dag.get_edge_info(pred.node_id, node_id)
            in_port = (port_for_anchor or {}).get(edge.destination_anchor, "data")
            # Upstream output port: filter fan-out picks filtered/excluded.
            out_port = self._output_port(pred, edge)
            result.append({"node": upstream_id, "input_port": in_port, "output_port": out_port})
        return result

    @staticmethod
    def _output_port(pred: IRNode, edge) -> str:
        """Designer output-port name for an upstream node given the edge anchor."""
        origin = edge.origin_anchor
        if isinstance(pred, FilterNode):
            if origin == "False":
                return "excluded_data"
            return "filtered_data"
        if isinstance(pred, JoinNode):
            # join@1 is single-output; L/R unmatched streams aren't represented.
            return "joined_data"
        return "data"

    # ── Cell construction / operator selection ──────────────────────────────

    def _build_cell(
        self,
        node: IRNode,
        dag: WorkflowDAG,
        id_map: dict[int, str],
        tiers: dict[int, int],
        lane_counter: dict[int, int],
    ) -> tuple[DesignerCell, list[str], bool]:
        """Return (cell, warnings, is_native). Native = clean visual operator."""
        pos = self._position(node, tiers, lane_counter)
        cell_id = _designer_id(node)
        name = node.annotation or node.original_tool_type or type(node).__name__.replace("Node", "")

        # ---- Native operators (business users see real visual nodes) ----
        if isinstance(node, ReadNode):
            return self._source_cell(node, cell_id, name, pos), [], True
        if isinstance(node, WriteNode):
            inputs = self._resolve_inputs(node.node_id, dag, id_map)
            return self._output_cell(node, cell_id, name, pos, inputs), [], True
        if isinstance(node, FilterNode):
            return self._filter_cell(node, cell_id, name, pos, dag, id_map)
        if isinstance(node, SortNode):
            inputs = self._resolve_inputs(node.node_id, dag, id_map)
            return self._sort_cell(node, cell_id, name, pos, inputs), [], True
        if isinstance(node, SampleNode) and node.n_records and node.sample_method == "first":
            inputs = self._resolve_inputs(node.node_id, dag, id_map)
            return self._limit_cell(node, cell_id, name, pos, inputs), [], True
        if isinstance(node, JoinNode):
            return self._join_cell(node, cell_id, name, pos, dag, id_map)
        if isinstance(node, UnionNode):
            inputs = self._resolve_inputs(node.node_id, dag, id_map)
            return self._combine_cell(node, cell_id, name, pos, inputs), [], True
        if isinstance(node, self._AGGREGATE_TYPES):
            inputs = self._resolve_inputs(node.node_id, dag, id_map)
            return self._aggregate_cell(node, cell_id, name, pos, inputs), [], True
        if isinstance(node, CrossTabNode):
            inputs = self._resolve_inputs(node.node_id, dag, id_map)
            cell, w = self._pivot_cell(node, cell_id, name, pos, inputs)
            return cell, w, True
        if isinstance(node, self._TRANSFORM_TYPES):
            inputs = self._resolve_inputs(node.node_id, dag, id_map)
            cell, w = self._transform_cell(node, cell_id, name, pos, inputs)
            return cell, w, True
        if isinstance(node, PythonToolNode):
            inputs = self._resolve_inputs(node.node_id, dag, id_map)
            return self._python_cell(node, cell_id, name, pos, inputs, code=node.code), [], True

        # ---- Fallback: sql/python operator via the tested SQL generator ----
        return self._fallback_cell(node, cell_id, name, pos, dag, id_map)

    # -- Native operator builders --------------------------------------------

    @staticmethod
    def _py(value: str) -> str:
        """Render a Python string literal safely (escapes quotes, backslashes,
        newlines). Used for interpolating user values — file paths (e.g.
        ``C:\\temp``), table names, expressions — into generated cell bodies.
        ``json.dumps`` produces a valid double-quoted Python string literal.
        """
        return json.dumps(value)

    def _source_cell(self, node: ReadNode, cell_id: str, name: str, pos: tuple[int, int]) -> DesignerCell:
        # Real Designer `source` config nests under table_source / file_source.
        config: dict[str, dict[str, object]]
        if node.source_type == "database" and node.table_name:
            config = {"table_source": {"tableName": node.table_name}}
            body = f"result = spark.read.table({self._py(node.table_name)})"
        else:
            fmt = (node.file_format or "csv").lower()
            path = node.file_path or "UNKNOWN_PATH"
            config = {"file_source": {"path": path, "format": fmt, "header": True, "inferSchema": True}}
            body = f"result = spark.read.format({self._py(fmt)}).load({self._py(path)})"
        return DesignerCell(
            cell_id=cell_id,
            template="source",
            name=name,
            position=pos,
            config=config,
            body=body,
            description=f"Source: {node.file_path or node.table_name}",
        )

    def _output_cell(
        self, node: WriteNode, cell_id: str, name: str, pos: tuple[int, int], inputs: list[dict]
    ) -> DesignerCell:
        target = node.table_name or node.file_path or "output_table"
        mode = node.write_mode or "overwrite"
        # Real Designer `output` config is {catalog, schema, table_name}. Split a
        # dotted target (catalog.schema.table); fall back to the configured
        # catalog/schema for shorter names.
        catalog, schema, table_name = self._split_target(target)
        config = {"catalog": catalog, "schema": schema, "table_name": table_name}
        fq = f"{catalog}.{schema}.{table_name}"
        body = f'inputs["data"].write.mode({self._py(mode)}).saveAsTable({self._py(fq)})'
        return DesignerCell(
            cell_id=cell_id,
            template="output",
            name=name,
            position=pos,
            config=config,
            inputs=inputs,
            body=body,
            description=f"Output: {target}",
        )

    def _split_target(self, target: str) -> tuple[str, str, str]:
        """Split a write target into (catalog, schema, table_name).

        Accepts ``catalog.schema.table``, ``schema.table``, or a bare name/file
        path; missing catalog/schema fall back to the conversion config.
        """
        default_catalog = getattr(self.config, "catalog_name", None) or "main"
        default_schema = getattr(self.config, "schema_name", None) or "default"
        # Strip a file extension for path-style targets (e.g. region_summary.csv).
        base = target.rsplit("/", 1)[-1]
        for ext in (".csv", ".parquet", ".json", ".avro", ".tsv", ".xlsx"):
            if base.lower().endswith(ext):
                base = base[: -len(ext)]
                break
        parts = base.split(".")
        if len(parts) >= 3:
            return parts[0], parts[1], ".".join(parts[2:])
        if len(parts) == 2:
            return default_catalog, parts[0], parts[1]
        return default_catalog, default_schema, parts[0]

    def _filter_cell(
        self,
        node: FilterNode,
        cell_id: str,
        name: str,
        pos: tuple[int, int],
        dag: WorkflowDAG,
        id_map: dict[int, str],
    ) -> tuple[DesignerCell, list[str], bool]:
        warnings: list[str] = []
        inputs = self._resolve_inputs(node.node_id, dag, id_map)
        if not node.expression or not node.expression.strip():
            warnings.append(f"Filter node {node.node_id} has no expression — passing all rows")
            condition = "true"
        else:
            try:
                condition = self._sql._translator.translate_string(node.expression)
            except Exception:
                condition = node.expression
                warnings.append(f"Designer filter expression fallback for node {node.node_id}")
        # filter@2 emits both filtered_data and excluded_data output ports.
        config = {"condition": condition}
        body = (
            f'filtered = inputs["data"].filter({self._py(condition)})\n'
            f'result = {{"filtered_data": filtered, '
            f'"excluded_data": inputs["data"].subtract(filtered)}}'
        )
        return (
            DesignerCell(
                cell_id=cell_id,
                template="filter",
                name=name,
                position=pos,
                config=config,
                inputs=inputs,
                body=body,
                description=f"Filter: {node.expression}",
            ),
            warnings,
            True,
        )

    def _sort_cell(
        self, node: SortNode, cell_id: str, name: str, pos: tuple[int, int], inputs: list[dict]
    ) -> DesignerCell:
        sort_expressions = [
            {
                "columnExpr": {"expr": sf.field_name, "type": "expr"},
                "sortBy": "ASC" if sf.ascending else "DESC",
            }
            for sf in node.sort_fields
        ]
        exprs = ", ".join(
            f"F.col({self._py(sf.field_name)}).{'asc' if sf.ascending else 'desc'}()" for sf in node.sort_fields
        )
        body = f'result = inputs["data"].orderBy({exprs})' if exprs else 'result = inputs["data"]'
        return DesignerCell(
            cell_id=cell_id,
            template="sort",
            name=name,
            position=pos,
            config={"sort_expressions": sort_expressions},
            inputs=inputs,
            body=body,
        )

    def _limit_cell(
        self, node: SampleNode, cell_id: str, name: str, pos: tuple[int, int], inputs: list[dict]
    ) -> DesignerCell:
        n = node.n_records or 100
        return DesignerCell(
            cell_id=cell_id,
            template="limit",
            name=name,
            position=pos,
            config={"limit": str(n)},
            inputs=inputs,
            body=f'result = inputs["data"].limit({n})',
        )

    def _join_cell(
        self,
        node: JoinNode,
        cell_id: str,
        name: str,
        pos: tuple[int, int],
        dag: WorkflowDAG,
        id_map: dict[int, str],
    ) -> tuple[DesignerCell, list[str], bool]:
        warnings: list[str] = []
        # Map only the explicit Left/Right anchors; everything else is assigned
        # positionally below (avoids the ambiguity where a generic "Input" anchor
        # would otherwise be forced to "left" and collide with a real Left edge).
        inputs = self._resolve_inputs(
            node.node_id,
            dag,
            id_map,
            port_for_anchor={"Left": "left", "Right": "right"},
        )
        # Assign the two join sides: honour explicit left/right, then fill the
        # remaining free slot(s) in connection order for any other anchors. The
        # body reads inputs["left"]/inputs["right"], so every input must land on
        # one of those two ports.
        taken = {inp["input_port"] for inp in inputs if inp["input_port"] in ("left", "right")}
        free_slots = [s for s in ("left", "right") if s not in taken]
        needs_assignment = [inp for inp in inputs if inp["input_port"] not in ("left", "right")]
        if needs_assignment:
            warnings.append(
                f"Join node {node.node_id}: input(s) on non-Left/Right anchors — "
                "assigning join sides by connection order; verify left vs. right."
            )
        for inp, slot in zip(needs_assignment, free_slots, strict=False):
            inp["input_port"] = slot
        jtype = (node.join_type or "inner").lower()
        # Real Designer `join` config: join_type + join_conditions (a single SQL
        # string using left./right. aliases) + optional expressions[].
        if node.join_keys:
            join_conditions = " AND ".join(f"left.{jk.left_field} = right.{jk.right_field}" for jk in node.join_keys)
            on = " & ".join(
                f"(F.col({self._py('l.' + jk.left_field)}) == F.col({self._py('r.' + jk.right_field)}))"
                for jk in node.join_keys
            )
            cond = f"[{on}]" if len(node.join_keys) == 1 else on
        else:
            join_conditions = ""
            cond = '"1=1"'
            warnings.append(f"Join node {node.node_id} has no keys — emitting cross/cartesian join")
        body = f'result = inputs["left"].alias("l").join(inputs["right"].alias("r"), {cond}, {self._py(jtype)})'
        return (
            DesignerCell(
                cell_id=cell_id,
                template="join",
                name=name,
                position=pos,
                config={"join_type": jtype, "join_conditions": join_conditions, "expressions": []},
                inputs=inputs,
                body=body,
            ),
            warnings,
            True,
        )

    def _combine_cell(
        self, node: UnionNode, cell_id: str, name: str, pos: tuple[int, int], inputs: list[dict]
    ) -> DesignerCell:
        # Real Designer `combine` uses positional data_0/data_1 input ports and
        # config {operator, quantifier}.
        for i, inp in enumerate(inputs):
            inp["input_port"] = f"data_{i}"
        body = (
            "from functools import reduce\n"
            "result = reduce(lambda a, b: a.unionByName(b, allowMissingColumns=True), "
            "[inputs[k] for k in sorted(inputs)])"
        )
        return DesignerCell(
            cell_id=cell_id,
            template="combine",
            name=name,
            position=pos,
            config={"operator": "UNION", "quantifier": "ALL"},
            inputs=inputs,
            body=body,
        )

    def _aggregate_cell(
        self, node: IRNode, cell_id: str, name: str, pos: tuple[int, int], inputs: list[dict]
    ) -> DesignerCell:
        # Real Designer `aggregate` config: group_bys[{expr,type}] +
        # aggregations[{columnExpr:{expr,type}, fn, alias}], fn UPPERCASE.
        if isinstance(node, CountRecordsNode):
            body = f'result = inputs["data"].agg(F.count(F.lit(1)).alias({self._py(node.output_field)}))'
            config = {
                "group_bys": [],
                "aggregations": [
                    {"columnExpr": {"expr": "1", "type": "expr"}, "fn": "COUNT", "alias": node.output_field}
                ],
            }
            return DesignerCell(
                cell_id=cell_id,
                template="aggregate",
                name=name,
                position=pos,
                config=config,
                inputs=inputs,
                body=body,
            )
        assert isinstance(node, SummarizeNode)
        group_bys: list[dict] = []
        aggregations: list[dict] = []
        agg_exprs: list[str] = []
        # IR AggAction → PySpark fn (body) and Designer fn name (config, uppercase).
        pyspark_fn = {
            AggAction.SUM: "sum",
            AggAction.COUNT: "count",
            AggAction.MIN: "min",
            AggAction.MAX: "max",
            AggAction.AVG: "avg",
            AggAction.FIRST: "first",
            AggAction.LAST: "last",
            AggAction.COUNT_DISTINCT: "countDistinct",
        }
        designer_fn = {
            AggAction.SUM: "SUM",
            AggAction.COUNT: "COUNT",
            AggAction.MIN: "MIN",
            AggAction.MAX: "MAX",
            AggAction.AVG: "AVG",
            AggAction.FIRST: "FIRST",
            AggAction.LAST: "LAST",
            AggAction.COUNT_DISTINCT: "COUNT",
        }
        for a in node.aggregations:
            if a.action == AggAction.GROUP_BY:
                group_bys.append({"expr": a.field_name, "type": "expr"})
                continue
            func = pyspark_fn.get(a.action, "count")
            alias = a.output_field_name or f"{a.action.value}_{a.field_name}"
            aggregations.append(
                {
                    "columnExpr": {"expr": a.field_name, "type": "expr"},
                    "fn": designer_fn.get(a.action, "COUNT"),
                    "alias": alias,
                }
            )
            agg_exprs.append(f"F.{func}({self._py(a.field_name)}).alias({self._py(alias)})")
        if not agg_exprs:
            agg_exprs.append('F.count(F.lit(1)).alias("count")')
        gb = ", ".join(self._py(g["expr"]) for g in group_bys)
        body = f'result = inputs["data"].groupBy({gb}).agg({", ".join(agg_exprs)})'
        return DesignerCell(
            cell_id=cell_id,
            template="aggregate",
            name=name,
            position=pos,
            config={"group_bys": group_bys, "aggregations": aggregations},
            inputs=inputs,
            body=body,
        )

    def _pivot_cell(
        self, node: CrossTabNode, cell_id: str, name: str, pos: tuple[int, int], inputs: list[dict]
    ) -> tuple[DesignerCell, list[str]]:
        warnings = [
            f"CrossTab (node {node.node_id}): Designer pivot needs the distinct header "
            f"values of `{node.header_field}` — review the generated pivot."
        ]
        gb = ", ".join(self._py(g) for g in node.group_fields)
        agg = (node.aggregation or "sum").lower()
        body = (
            f'result = inputs["data"].groupBy({gb})'
            f".pivot({self._py(node.header_field)}).{agg}({self._py(node.value_field)})"
        )
        # Real Designer `pivot` config (pivot mode). Group-by columns are the
        # ones NOT pivoted, expressed via exclude_columns.
        exclude_columns = [
            {"expr": node.header_field, "type": "column"},
            {"expr": node.value_field, "type": "column"},
        ]
        return (
            DesignerCell(
                cell_id=cell_id,
                template="pivot",
                name=name,
                position=pos,
                config={
                    "mode": "pivot",
                    "pivot_column": node.header_field,
                    "value_column": node.value_field,
                    "agg_fn": (node.aggregation or "sum").upper(),
                    "null_behavior": "zero",
                    "unpivot_columns": [],
                    "exclude_columns": exclude_columns,
                },
                inputs=inputs,
                body=body,
            ),
            warnings,
        )

    def _transform_cell(
        self, node: IRNode, cell_id: str, name: str, pos: tuple[int, int], inputs: list[dict]
    ) -> tuple[DesignerCell, list[str]]:
        """Select / Formula / DataCleansing → Designer ``transform``.

        Real Designer `transform` config is ``expressions``: a list of
        selectExpr strings (``"*"``, ``"col"``, ``"<expr> AS `alias`"``). We keep
        the PySpark body in step with that expression list.
        """
        warnings: list[str] = []
        # A drop-only Select rewrites the projection; otherwise start from "*"
        # (keep all upstream columns) and append computed/renamed columns.
        expressions: list[str] = []
        lines: list[str] = ['df = inputs["data"]']
        drop_only = False

        if isinstance(node, SelectNode):
            drops = [
                op.field_name for op in node.field_operations if not op.selected or op.action == FieldAction.DESELECT
            ]
            renames = [
                (op.field_name, op.rename_to)
                for op in node.field_operations
                if op.action == FieldAction.RENAME and op.rename_to
            ]
            if drops and not renames:
                # Express as an explicit exclusion: * EXCEPT is not portable, so
                # drop in the body and mirror with a "* minus dropped" note. The
                # config uses "*" plus body drops (Designer runs the body).
                drop_only = True
                expressions.append("*")
                for d in drops:
                    lines.append(f"df = df.drop({self._py(d)})")
            else:
                if drops:
                    for d in drops:
                        lines.append(f"df = df.drop({self._py(d)})")
                expressions.append("*")
                for src, dst in renames:
                    expressions.append(f"`{src}` AS `{dst}`")
                    lines.append(f"df = df.withColumnRenamed({self._py(src)}, {self._py(dst)})")
        elif isinstance(node, FormulaNode):
            expressions.append("*")
            for f in node.formulas:
                try:
                    expr = self._sql._translator.translate_string(f.expression)
                except Exception:
                    expr = "NULL"
                    warnings.append(f"Designer formula fallback: {f.output_field}")
                expressions.append(f"{expr} AS `{f.output_field}`")
                lines.append(f"df = df.withColumn({self._py(f.output_field)}, F.expr({self._py(expr)}))")
        elif isinstance(node, DataCleansingNode):
            expressions.append("*")
            for fld in node.fields:
                expr = f"`{fld}`"
                if node.trim_whitespace:
                    expr = f"trim({expr})"
                if node.modify_case == "upper":
                    expr = f"upper({expr})"
                elif node.modify_case == "lower":
                    expr = f"lower({expr})"
                elif node.modify_case == "title":
                    expr = f"initcap({expr})"
                expressions.append(f"{expr} AS `{fld}`")
                lines.append(f"df = df.withColumn({self._py(fld)}, F.expr({self._py(expr)}))")

        if not expressions:
            expressions.append("*")
        _ = drop_only  # (kept for readability of the drop-only branch above)
        lines.append("result = df")
        return (
            DesignerCell(
                cell_id=cell_id,
                template="transform",
                name=name,
                position=pos,
                config={"expressions": expressions},
                inputs=inputs,
                body="\n".join(lines),
            ),
            warnings,
        )

    def _python_cell(
        self,
        node: IRNode,
        cell_id: str,
        name: str,
        pos: tuple[int, int],
        inputs: list[dict],
        code: str,
    ) -> DesignerCell:
        # python operator: single variadic ``data`` input port (list of upstreams).
        for inp in inputs:
            inp["input_port"] = "data"
        body = code.strip() or 'result = inputs["data"][0] if inputs.get("data") else None'
        return DesignerCell(
            cell_id=cell_id,
            template="python",
            name=name,
            position=pos,
            config={"code": body},
            inputs=inputs,
            body=body,
        )

    def _markdown_cell(self, node: CommentNode, pos: tuple[int, int]) -> DesignerCell:
        text = node.comment_text or ""
        return DesignerCell(
            cell_id=_designer_id(node),
            template="markdown",
            name="Note",
            position=pos,
            config={"md": text},
            body="",
        )

    def _fallback_cell(
        self,
        node: IRNode,
        cell_id: str,
        name: str,
        pos: tuple[int, int],
        dag: WorkflowDAG,
        id_map: dict[int, str],
    ) -> tuple[DesignerCell, list[str], bool]:
        """Anything without a native operator → a ``sql`` operator cell.

        Reuses :meth:`SQLGenerator._generate_cte_body` (covers all 59 IR node
        types) to produce a SELECT, then references upstreams by their cell id
        so the Designer sql operator resolves inputs by name.
        """
        # Build a name→id CTE map so the SQL body references upstream cell ids.
        cte_map = {p.node_id: id_map.get(p.node_id, _cte_name(p)) for p in dag.get_predecessors(node.node_id)}
        input_ctes = self._sql._resolve_input_ctes(node.node_id, dag, cte_map)
        sql_body, warnings = self._sql._generate_cte_body(node, input_ctes)
        inputs = self._resolve_inputs(node.node_id, dag, id_map)
        return (
            DesignerCell(
                cell_id=cell_id,
                template="sql",
                name=name,
                position=pos,
                config={"query": sql_body},
                inputs=inputs,
                body=f"# SQL operator\n# {sql_body}",
            ),
            warnings,
            False,
        )

    # ── Notebook assembly ────────────────────────────────────────────────────

    def _assemble_notebook(self, cells: list[DesignerCell], workflow_name: str) -> str:
        nb_cells = [self._to_ipynb_cell(c) for c in cells]
        notebook = {
            "cells": nb_cells,
            "metadata": {
                "application/vnd.databricks.v1+notebook": {
                    "computePreferences": None,
                    "dashboards": [],
                    "environmentMetadata": None,
                    "inputWidgetPreferences": None,
                    "language": "python",
                    "notebookMetadata": {"pythonIndentUnit": 4},
                    "notebookName": workflow_name,
                    "widgets": {},
                },
                "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": "python3",
                },
                "language_info": {"name": "python"},
            },
            "nbformat": 4,
            "nbformat_minor": 0,
        }
        return json.dumps(notebook, indent=1) + "\n"

    def _to_ipynb_cell(self, cell: DesignerCell) -> dict:
        source = self._render_source(cell)
        return {
            "cell_type": "code",
            "source": source.splitlines(keepends=True),
            "metadata": {
                "application/vnd.databricks.v1+cell": {
                    "cellMetadata": {},
                    "inputWidgets": {},
                    "nuid": str(uuid.uuid4()),
                    "showTitle": False,
                    "tableResultSettingsMap": {},
                    "title": "",
                }
            },
            "outputs": [],
            "execution_count": 0,
        }

    def _render_source(self, cell: DesignerCell) -> str:
        annotation = self._render_annotation(cell)
        parts = [f'"""\n{annotation}"""']
        if cell.body:
            parts.append(cell.body)
        return "\n".join(parts) + "\n"

    def _render_annotation(self, cell: DesignerCell) -> str:
        version = OPERATOR_VERSIONS.get(cell.template, "1.0.0")
        lines: list[str] = [
            f"id: {cell.cell_id}",
            f"template: {cell.template}",
            f"templateVersion: {version}",
            f"name: {self._yaml_scalar(cell.name)}",
            "position:",
            f"  x: {cell.position[0]}",
            f"  y: {cell.position[1]}",
            "description:",
            f"  text: {self._yaml_scalar(cell.description)}",
            '  hash: ""',
            'previewCodeHash: ""',
            'previewMode: "1000"',
        ]
        lines.extend(self._render_config(cell.config))
        lines.extend(self._render_inputs(cell.inputs))
        return "\n".join(lines) + "\n"

    def _render_config(self, config: dict) -> list[str]:
        if not config:
            return ["config: {}"]
        lines = ["config:"]
        lines.extend(self._render_yaml_value(config, indent=1))
        return lines

    def _render_inputs(self, inputs: list[dict]) -> list[str]:
        if not inputs:
            return ["input: []"]
        lines = ["input:"]
        for inp in inputs:
            lines.append(f"  - node: {self._yaml_scalar(inp['node'])}")
            lines.append(f"    input_port: {self._yaml_scalar(inp['input_port'])}")
            lines.append(f"    output_port: {self._yaml_scalar(inp['output_port'])}")
        return lines

    def _render_yaml_value(self, value, indent: int) -> list[str]:
        """Render a nested dict/list/scalar as indented YAML lines."""
        pad = "  " * indent
        lines: list[str] = []
        if isinstance(value, dict):
            if not value:
                return [f"{pad}{{}}"]
            for k, v in value.items():
                if (isinstance(v, dict) and v) or (isinstance(v, list) and v):
                    lines.append(f"{pad}{k}:")
                    lines.extend(self._render_yaml_value(v, indent + 1))
                elif isinstance(v, (dict | list)):
                    lines.append(f"{pad}{k}: {'{}' if isinstance(v, dict) else '[]'}")
                else:
                    # All scalars — including multi-line code/query strings — go
                    # through _yaml_scalar, which emits a safely-escaped
                    # double-quoted scalar (see its docstring for why we avoid
                    # YAML block literals here).
                    lines.append(f"{pad}{k}: {self._yaml_scalar(v)}")
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    # Render the dict at indent+1, then hoist the first line under
                    # the "- " marker so nested dict/list values stay well-formed.
                    sub = self._render_yaml_value(item, indent + 1)
                    if sub:
                        first = sub[0].lstrip()
                        lines.append(f"{pad}- {first}")
                        lines.extend(sub[1:])
                    else:
                        lines.append(f"{pad}- {{}}")
                else:
                    lines.append(f"{pad}- {self._yaml_scalar(item)}")
        else:
            lines.append(f"{pad}{self._yaml_scalar(value)}")
        return lines

    @staticmethod
    def _yaml_scalar(value) -> str:
        """Quote a scalar per Designer's YAML rules to avoid silent cell drops.

        Multi-line values are emitted as a double-quoted scalar with escaped
        newlines rather than a YAML block literal (``|``): a block literal is
        fragile (a leading-whitespace or under-indented content line makes the
        whole annotation unparseable) and, because the annotation itself lives
        inside a Python ``\"\"\"`` docstring, any embedded ``\"\"\"`` in a raw
        block would also terminate the docstring early. A double-quoted,
        fully-escaped scalar round-trips safely on both counts.
        """
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int | float)):
            return str(value)
        s = "" if value is None else str(value)
        # Force-quote when the value contains control chars (newline/tab/CR) —
        # these don't match the printable-char trigger set but must be escaped.
        has_control = any(c in s for c in ("\n", "\r", "\t"))
        if s.lower() in _YAML_BOOLISH or has_control or _QUOTE_TRIGGERS.search(s):
            escaped = s.replace("\\", "\\\\").replace('"', '\\"')
            escaped = escaped.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
            return f'"{escaped}"'
        return s
