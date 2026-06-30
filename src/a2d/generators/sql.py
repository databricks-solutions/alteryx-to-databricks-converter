"""Databricks SQL generator using CTEs.

Walks a :class:`~a2d.ir.graph.WorkflowDAG` and produces a SQL file where
each step is a Common Table Expression (CTE).
"""

from __future__ import annotations

import logging
import re

from a2d.config import ConversionConfig
from a2d.expressions.base_translator import BaseTranslationError
from a2d.expressions.sql_translator import SparkSQLTranslator
from a2d.generators.base import CodeGenerator, GeneratedFile, GeneratedOutput
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    AggAction,
    AppendFieldsNode,
    AutoFieldNode,
    BrowseNode,
    BufferNode,
    ChartNode,
    CloudStorageNode,
    CommentNode,
    CountRecordsNode,
    CreatePointsNode,
    CrossTabNode,
    DataCleansingNode,
    DateTimeNode,
    DistanceNode,
    DownloadNode,
    DynamicInputNode,
    DynamicOutputNode,
    DynamicRenameNode,
    EmailOutputNode,
    FieldAction,
    FieldSummaryNode,
    FilterNode,
    FindNearestNode,
    FindReplaceNode,
    FormulaNode,
    GenerateRowsNode,
    GeocoderNode,
    ImputationNode,
    IRNode,
    JoinMultipleNode,
    JoinNode,
    JsonParseNode,
    LiteralDataNode,
    MacroIONode,
    MakeGridNode,
    MultiFieldFormulaNode,
    MultiRowFormulaNode,
    PredictiveModelNode,
    PythonToolNode,
    ReadNode,
    RecordIDNode,
    RegExNode,
    ReportNode,
    RunCommandNode,
    RunningTotalNode,
    SampleNode,
    SelectNode,
    SortNode,
    SpatialMatchNode,
    SummarizeNode,
    TextToColumnsNode,
    TileNode,
    TradeAreaNode,
    TransposeNode,
    UnionNode,
    UniqueNode,
    UnsupportedNode,
    WeightedAverageNode,
    WidgetNode,
    WorkflowControlNode,
    WriteNode,
    XMLParseNode,
)
from a2d.utils.types import alteryx_fmt_to_spark, normalize_sql_for_spark

logger = logging.getLogger("a2d.generators.sql")


def _cte_name(node: IRNode) -> str:
    """Generate a CTE name from an IR node."""
    tool = node.original_tool_type or type(node).__name__.replace("Node", "")
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", tool).lower()
    return f"step_{node.node_id}_{safe}"


class SQLGenerator(CodeGenerator):
    """Generate Databricks SQL with CTEs for each step."""

    # Node types that are pure passthroughs — skip CTE, forward predecessor name
    _PASSTHROUGH_TYPES = (AutoFieldNode, BrowseNode, WorkflowControlNode)

    def __init__(self, config: ConversionConfig) -> None:
        super().__init__(config)
        self._translator = SparkSQLTranslator()

    def generate(self, dag: WorkflowDAG, workflow_name: str = "workflow") -> GeneratedOutput:
        ordered_nodes = dag.topological_order()
        warnings: list[str] = []
        cte_map: dict[int, str] = {}  # node_id -> cte name
        cte_blocks: list[str] = []
        last_cte: str = "empty"
        node_count = 0
        unsupported_count = 0

        passthrough_types = self._PASSTHROUGH_TYPES

        for node in ordered_nodes:
            if isinstance(node, CommentNode):
                comment_lines = (node.comment_text or "").replace("\n", "\n-- ")
                cte_blocks.append(f"-- {comment_lines}")
                continue

            # Skip no-op passthrough nodes: forward the predecessor's CTE name
            if isinstance(node, passthrough_types):
                input_ctes = self._resolve_input_ctes(node.node_id, dag, cte_map)
                prev_cte = self._get_single_input(input_ctes) if input_ctes else None
                if prev_cte:
                    cte_map[node.node_id] = prev_cte
                    node_count += 1
                    continue

            name = _cte_name(node)
            cte_map[node.node_id] = name

            input_ctes = self._resolve_input_ctes(node.node_id, dag, cte_map)
            sql_body, step_warnings = self._generate_cte_body(node, input_ctes)
            warnings.extend(step_warnings)

            indented = sql_body.replace("\n", "\n    ")
            cte_blocks.append(f"{name} AS (\n    {indented}\n)")
            last_cte = name
            node_count += 1
            if isinstance(node, UnsupportedNode):
                unsupported_count += 1

        # Build full SQL
        self.metadata["stats"] = {
            "total_nodes": node_count,
            "supported_nodes": node_count - unsupported_count,
            "unsupported_nodes": unsupported_count,
            "warnings": len(warnings),
        }

        meta_header = self._build_header_lines(workflow_name, "--")
        header = "\n".join(meta_header) + "\n\n"

        if cte_blocks:
            # Separate comments and real CTEs
            real_ctes = []
            preamble_comments = []
            for block in cte_blocks:
                if block.startswith("--"):
                    preamble_comments.append(block)
                else:
                    real_ctes.append(block)

            comments_str = "\n".join(preamble_comments) + "\n" if preamble_comments else ""
            ctes_str = ",\n".join(real_ctes)
            sql = f"{header}{comments_str}WITH {ctes_str}\nSELECT * FROM {last_cte};\n"
        else:
            sql = f"{header}SELECT 1;\n"

        # Append footer
        footer_lines = self._build_footer_lines(sql, "--")
        sql += "\n" + "\n".join(footer_lines) + "\n"

        files = [
            GeneratedFile(
                filename=f"{workflow_name}.sql",
                content=sql,
                file_type="sql",
            )
        ]

        stats = {
            "total_nodes": node_count,
            "supported_nodes": node_count - unsupported_count,
            "unsupported_nodes": unsupported_count,
            "total_ctes": len([b for b in cte_blocks if not b.startswith("--")]),
            "warnings": len(warnings),
        }

        return GeneratedOutput(files=files, warnings=warnings, stats=stats)

    # -- Helpers ------------------------------------------------------------

    def _resolve_input_ctes(self, node_id: int, dag: WorkflowDAG, cte_map: dict[int, str]) -> dict[str, str]:
        """Map destination anchors to upstream CTE names."""
        result: dict[str, str] = {}
        preds = dag.get_predecessors(node_id)
        for pred in preds:
            edge_info = dag.get_edge_info(pred.node_id, node_id)
            dest_anchor = edge_info.destination_anchor
            result[dest_anchor] = cte_map.get(pred.node_id, f"step_{pred.node_id}_unknown")
        return result

    def _generate_cte_body(self, node: IRNode, input_ctes: dict[str, str]) -> tuple[str, list[str]]:
        """Generate the SQL body for a CTE."""
        warnings: list[str] = []

        if isinstance(node, ReadNode):
            return self._sql_ReadNode(node), warnings

        if isinstance(node, WriteNode):
            inp = self._get_single_input(input_ctes)
            return f"SELECT * FROM {inp} /* Write to: {node.file_path or node.table_name} */", warnings

        if isinstance(node, LiteralDataNode):
            if node.data_rows and node.field_names:
                selects = []
                for row in node.data_rows:
                    parts = []
                    for i, v in enumerate(row):
                        escaped = str(v).replace("'", "''")
                        if i < len(node.field_names):
                            parts.append(f"'{escaped}' AS `{node.field_names[i]}`")
                        else:
                            parts.append(f"'{escaped}'")
                    selects.append(f"SELECT {', '.join(parts)}")
                return " UNION ALL ".join(selects), warnings
            return "SELECT 1 WHERE FALSE /* empty literal data */", warnings

        if isinstance(node, BrowseNode):
            inp = self._get_single_input(input_ctes)
            return f"SELECT * FROM {inp} /* Browse preview */", warnings

        if isinstance(node, FilterNode):
            inp = self._get_single_input(input_ctes)
            if not node.expression or not node.expression.strip():
                warnings.append(f"Filter node {node.node_id} has no expression — returning all rows")
                return (
                    f"SELECT * FROM {inp} /* TODO: Filter node {node.node_id} — expression not found in workflow XML */",
                    warnings,
                )
            try:
                expr = self._translator.translate_string(node.expression)
            except BaseTranslationError:
                expr = node.expression
                warnings.append(f"SQL filter expression fallback for node {node.node_id}")
            return f"SELECT * FROM {inp} WHERE {expr}", warnings

        if isinstance(node, FormulaNode):
            result = self._get_single_input(input_ctes)
            for formula in node.formulas:
                try:
                    expr = self._translator.translate_string(formula.expression)
                except BaseTranslationError:
                    # NULL placeholder keeps the SQL syntactically valid;
                    # the original expression is preserved in a comment so
                    # the user can manually translate.
                    expr = f"NULL /* TODO: {formula.expression} */"
                    warnings.append(f"SQL formula fallback: {formula.output_field}")
                result = f"SELECT *, {expr} AS `{formula.output_field}` FROM ({result})"
            return result, warnings

        if isinstance(node, SelectNode):
            inp = self._get_single_input(input_ctes)
            cols = []
            drops = set()
            for op in node.field_operations:
                if not op.selected or op.action == FieldAction.DESELECT:
                    drops.add(op.field_name)
                elif op.action == FieldAction.RENAME and op.rename_to:
                    cols.append(f"`{op.field_name}` AS `{op.rename_to}`")
            if drops and not cols:
                # Use SELECT * EXCEPT pattern (Databricks SQL supports this)
                drop_list = ", ".join(f"`{d}`" for d in drops)
                return f"SELECT * EXCEPT ({drop_list}) FROM {inp}", warnings
            if cols:
                col_str = ", ".join(cols)
                return f"SELECT *, {col_str} FROM {inp}", warnings
            return f"SELECT * FROM {inp}", warnings

        if isinstance(node, SortNode):
            inp = self._get_single_input(input_ctes)
            parts = []
            for sf in node.sort_fields:
                direction = "ASC" if sf.ascending else "DESC"
                nulls = ""
                if sf.nulls_first is True:
                    nulls = " NULLS FIRST"
                elif sf.nulls_first is False:
                    nulls = " NULLS LAST"
                parts.append(f"`{sf.field_name}` {direction}{nulls}")
            order = ", ".join(parts)
            return f"SELECT * FROM {inp} ORDER BY {order}", warnings

        if isinstance(node, SampleNode):
            inp = self._get_single_input(input_ctes)
            if node.n_records:
                return f"SELECT * FROM {inp} LIMIT {node.n_records}", warnings
            if node.percentage:
                return f"SELECT * FROM {inp} TABLESAMPLE ({node.percentage} PERCENT)", warnings
            return f"SELECT * FROM {inp} LIMIT 100", warnings

        if isinstance(node, UniqueNode):
            inp = self._get_single_input(input_ctes)
            if node.key_fields:
                keys = ", ".join(f"`{k}`" for k in node.key_fields)
                return (
                    f"SELECT * FROM {inp} QUALIFY ROW_NUMBER() OVER (PARTITION BY {keys} ORDER BY {keys}) = 1",
                    warnings,
                )
            return f"SELECT DISTINCT * FROM {inp}", warnings

        if isinstance(node, RecordIDNode):
            inp = self._get_single_input(input_ctes)
            return (
                f"SELECT *, ROW_NUMBER() OVER (ORDER BY 1) + {node.starting_value - 1} AS `{node.output_field}` FROM {inp}",
                warnings,
            )

        if isinstance(node, AutoFieldNode):
            inp = self._get_single_input(input_ctes)
            return f"SELECT * FROM {inp} /* AutoField passthrough */", warnings

        if isinstance(node, DynamicRenameNode):
            inp = self._get_single_input(input_ctes)
            mode = node.rename_mode or "FirstRow"
            # NOTE: don't include the literal word "Formula"/"formula"/"expression"/etc.
            # in this warning — the audit CSV builder matches those keywords to flag
            # expression failures, which would mis-classify unrelated rows.
            mode_label = mode.replace("Formula", "from-input")
            warnings.append(f"DynamicRename node {node.node_id} ({mode_label} mode): manual SQL rewrite needed")
            if mode == "FirstRow":
                # SQL has no clean way to promote the first row to headers.
                return (
                    f"SELECT * FROM {inp} "
                    f"/* TODO: DynamicRename (FirstRow) — promote first row to headers; "
                    f"do this upstream in PySpark/pandas or pre-process the source */",
                    warnings,
                )
            return (
                f"SELECT * FROM {inp} "
                f"/* TODO: DynamicRename mode={mode} — apply rename map manually "
                f"using SELECT col AS new_col, ... */",
                warnings,
            )

        if isinstance(node, JoinNode):
            left = input_ctes.get("Left", input_ctes.get("Input", "MISSING_LEFT"))
            right = input_ctes.get("Right", "MISSING_RIGHT")
            jtype = (node.join_type or "inner").upper()
            if node.join_keys:
                on_parts = [f"{left}.`{jk.left_field}` = {right}.`{jk.right_field}`" for jk in node.join_keys]
                on_clause = " AND ".join(on_parts)
            else:
                on_clause = "TRUE"
            return f"SELECT * FROM {left} {jtype} JOIN {right} ON {on_clause}", warnings

        if isinstance(node, UnionNode):
            tables = list(input_ctes.values())
            if not tables:
                return "SELECT 1 WHERE FALSE", warnings
            parts = [f"SELECT * FROM {t}" for t in tables]
            return " UNION ALL ".join(parts), warnings

        if isinstance(node, AppendFieldsNode):
            target = input_ctes.get("Target", input_ctes.get("Input", "MISSING"))
            source = input_ctes.get("Source", "MISSING")
            warnings.append(
                f"AppendFields node {node.node_id}: CROSS JOIN — verify source is a single-row lookup. "
                "If source has multiple rows, output will be target_rows x source_rows."
            )
            return f"SELECT * FROM {target} CROSS JOIN {source}", warnings

        if isinstance(node, SummarizeNode):
            inp = self._get_single_input(input_ctes)
            gb = []
            aggs = []
            sql_agg = {
                AggAction.SUM: "SUM",
                AggAction.COUNT: "COUNT",
                AggAction.COUNT_DISTINCT: "COUNT(DISTINCT",
                AggAction.MIN: "MIN",
                AggAction.MAX: "MAX",
                AggAction.AVG: "AVG",
                AggAction.FIRST: "FIRST",
                AggAction.LAST: "LAST",
            }
            for a in node.aggregations:
                if a.action == AggAction.GROUP_BY:
                    gb.append(f"`{a.field_name}`")
                elif a.action == AggAction.COUNT_DISTINCT:
                    alias = a.output_field_name or f"{a.action.value}_{a.field_name}"
                    aggs.append(f"COUNT(DISTINCT `{a.field_name}`) AS `{alias}`")
                elif a.action in sql_agg:
                    func = sql_agg[a.action]
                    alias = a.output_field_name or f"{a.action.value}_{a.field_name}"
                    aggs.append(f"{func}(`{a.field_name}`) AS `{alias}`")
                else:
                    alias = a.output_field_name or f"{a.action.value}_{a.field_name}"
                    aggs.append(f"COUNT(`{a.field_name}`) AS `{alias}`")

            select_parts = gb + (aggs if aggs else ["COUNT(*) AS `count`"])
            select_str = ", ".join(select_parts)
            if gb:
                gb_str = ", ".join(gb)
                return f"SELECT {select_str} FROM {inp} GROUP BY {gb_str}", warnings
            return f"SELECT {select_str} FROM {inp}", warnings

        if isinstance(node, CrossTabNode):
            inp = self._get_single_input(input_ctes)
            gcols = ", ".join(f"`{g}`" for g in node.group_fields)
            warnings.append(
                f"CrossTab (node {node.node_id}): PIVOT requires explicit values in the IN clause. "
                f"Replace 'TODO_VALUE_1', 'TODO_VALUE_2' with actual distinct values of `{node.header_field}`."
            )
            return (
                f"SELECT * FROM ("
                f"SELECT {gcols}, `{node.header_field}`, `{node.value_field}` FROM {inp}"
                f") PIVOT ({node.aggregation.upper()}(`{node.value_field}`) "
                f"FOR `{node.header_field}` IN ('TODO_VALUE_1', 'TODO_VALUE_2'))",
                warnings,
            )

        if isinstance(node, CountRecordsNode):
            inp = self._get_single_input(input_ctes)
            return f"SELECT COUNT(*) AS `{node.output_field}` FROM {inp}", warnings

        if isinstance(node, MultiRowFormulaNode):
            inp = self._get_single_input(input_ctes)
            try:
                expr = self._translator.translate_string(node.expression)
                expr = expr.replace("OVER (window)", "OVER (ORDER BY 1)")
            except BaseTranslationError:
                expr = node.expression
                warnings.append(f"MultiRowFormula SQL fallback for node {node.node_id}")
            if node.group_fields:
                partition = ", ".join(f"`{gf}`" for gf in node.group_fields)
                window = f"PARTITION BY {partition} ORDER BY 1"
            else:
                window = "ORDER BY 1"
            expr = expr.replace("OVER (ORDER BY 1)", f"OVER ({window})")
            return f"SELECT *, {expr} AS `{node.output_field}` FROM {inp}", warnings

        if isinstance(node, MultiFieldFormulaNode):
            inp = self._get_single_input(input_ctes)
            extras = []
            for fld in node.fields:
                try:
                    expr_str = node.expression.replace("[_CurrentField_]", f"[{fld}]")
                    expr = self._translator.translate_string(expr_str)
                except BaseTranslationError:
                    expr = f"`{fld}`"
                    warnings.append(f"MultiFieldFormula SQL fallback for field '{fld}'")
                output_name = f"{fld}_out" if node.copy_output else fld
                extras.append(f"{expr} AS `{output_name}`")
            extra_str = ", ".join(extras)
            return f"SELECT *, {extra_str} FROM {inp}", warnings

        if isinstance(node, DataCleansingNode):
            inp = self._get_single_input(input_ctes)
            select_parts = ["*"]
            for fld in node.fields:
                expr = f"`{fld}`"
                if node.trim_whitespace:
                    expr = f"TRIM({expr})"
                if node.remove_null:
                    replace_val = f"'{node.replace_nulls_with}'" if node.replace_nulls_with else "''"
                    expr = f"COALESCE({expr}, {replace_val})"
                if node.modify_case == "upper":
                    expr = f"UPPER({expr})"
                elif node.modify_case == "lower":
                    expr = f"LOWER({expr})"
                elif node.modify_case == "title":
                    expr = f"INITCAP({expr})"
                if expr != f"`{fld}`":
                    select_parts.append(f"{expr} AS `{fld}`")
            sel = ", ".join(select_parts)
            return f"SELECT {sel} FROM {inp}", warnings

        if isinstance(node, GenerateRowsNode):
            output_field = node.output_field or "GeneratedRow"
            range_match = re.search(r"(\w+)\s*<=?\s*(\d+)", node.condition_expression)
            init_match = re.search(r"(\w+)\s*=\s*(\d+)", node.init_expression)
            if init_match and range_match:
                start_val = int(init_match.group(2))
                end_val = int(range_match.group(2))
                if "<=" in node.condition_expression:
                    end_val += 1
                return f"SELECT id AS `{output_field}` FROM range({start_val}, {end_val})", warnings
            return f"SELECT id AS `{output_field}` FROM range(0, 1000) /* Adjust range */", warnings

        if isinstance(node, FindReplaceNode):
            target = self._get_single_input(input_ctes)
            lookup = input_ctes.get("Source", input_ctes.get("Right", target))
            find_field = node.find_field or "find_field"
            replace_field = node.replace_field or "replace_field"
            return (
                f"SELECT t.*, COALESCE(l.`{replace_field}`, t.`{find_field}`) AS `{find_field}_replaced` "
                f"FROM {target} t LEFT JOIN {lookup} l ON t.`{find_field}` = l.`{find_field}`"
            ), warnings

        if isinstance(node, JoinMultipleNode):
            tables = list(input_ctes.values())
            if len(tables) < 2:
                return f"SELECT * FROM {tables[0] if tables else 'MISSING'}", warnings
            join_type = (node.join_type or "inner").upper()
            sql = f"SELECT * FROM {tables[0]}"
            for tbl in tables[1:]:
                if node.join_keys:
                    on_parts = [f"{tables[0]}.`{jk.left_field}` = {tbl}.`{jk.right_field}`" for jk in node.join_keys]
                    on_clause = " AND ".join(on_parts)
                    sql += f" {join_type} JOIN {tbl} ON {on_clause}"
                else:
                    sql += f" NATURAL {join_type} JOIN {tbl}"
            return sql, warnings

        if isinstance(node, RegExNode):
            inp = self._get_single_input(input_ctes)
            if node.mode == "replace":
                return (
                    f"SELECT *, REGEXP_REPLACE(`{node.field_name}`, '{node.expression}', '{node.replacement}') AS `{node.field_name}` FROM {inp}",
                    warnings,
                )
            elif node.mode == "parse":
                extras = []
                for idx, out_field in enumerate(node.output_fields):
                    extras.append(
                        f"REGEXP_EXTRACT(`{node.field_name}`, '{node.expression}', {idx + 1}) AS `{out_field}`"
                    )
                extra_str = ", ".join(extras)
                return f"SELECT *, {extra_str} FROM {inp}", warnings
            elif node.mode == "match":
                return f"SELECT *, `{node.field_name}` RLIKE '{node.expression}' AS `_regex_match` FROM {inp}", warnings
            return f"SELECT * FROM {inp} /* RegEx mode '{node.mode}' - manual conversion */", warnings

        if isinstance(node, TextToColumnsNode):
            inp = self._get_single_input(input_ctes)
            root = node.output_root_name or node.field_name
            if node.split_to == "rows":
                return (
                    f"SELECT *, EXPLODE(SPLIT(`{node.field_name}`, '{node.delimiter}')) AS `{root}` FROM {inp}",
                    warnings,
                )
            extras = []
            num = node.num_columns or 5
            for i in range(num):
                extras.append(f"SPLIT(`{node.field_name}`, '{node.delimiter}')[{i}] AS `{root}_{i + 1}`")
            extra_str = ", ".join(extras)
            return f"SELECT *, {extra_str} FROM {inp}", warnings

        if isinstance(node, DateTimeNode):
            inp = self._get_single_input(input_ctes)
            out_field = node.output_field or f"{node.input_field}_converted"
            fmt = alteryx_fmt_to_spark(node.format_string or "yyyy-MM-dd")
            if node.conversion_mode == "parse":
                return f"SELECT *, TO_DATE(`{node.input_field}`, '{fmt}') AS `{out_field}` FROM {inp}", warnings
            elif node.conversion_mode == "format":
                return f"SELECT *, DATE_FORMAT(`{node.input_field}`, '{fmt}') AS `{out_field}` FROM {inp}", warnings
            elif node.conversion_mode == "now":
                return f"SELECT *, CURRENT_TIMESTAMP() AS `{out_field}` FROM {inp}", warnings
            return f"SELECT *, `{node.input_field}` AS `{out_field}` FROM {inp}", warnings

        if isinstance(node, JsonParseNode):
            inp = self._get_single_input(input_ctes)
            out_field = node.output_field or f"{node.input_field}_parsed"
            return f"SELECT *, GET_JSON_OBJECT(`{node.input_field}`, '$') AS `{out_field}` FROM {inp}", warnings

        if isinstance(node, TransposeNode):
            inp = self._get_single_input(input_ctes)
            if node.data_fields:
                cols_str = ", ".join(f"'{df}', `{df}`" for df in node.data_fields)
                key_cols = ", ".join(f"`{kf}`" for kf in node.key_fields) if node.key_fields else ""
                key_part = f"{key_cols}, " if key_cols else ""
                return (
                    f"SELECT {key_part}stack({len(node.data_fields)}, {cols_str}) AS (`{node.header_name}`, `{node.value_name}`) FROM {inp}",
                    warnings,
                )
            warnings.append(f"Transpose (node {node.node_id}): data columns need manual specification")
            return f"SELECT * FROM {inp} /* UNPIVOT needs manual column specification */", warnings

        if isinstance(node, RunningTotalNode):
            inp = self._get_single_input(input_ctes)
            extras = []
            if node.group_fields:
                partition = ", ".join(f"`{gf}`" for gf in node.group_fields)
                window = f"PARTITION BY {partition} ORDER BY 1 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW"
            else:
                window = "ORDER BY 1 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW"
            func_map = {"Sum": "SUM", "Avg": "AVG", "Count": "COUNT", "Min": "MIN", "Max": "MAX"}
            for rf in node.running_fields:
                func = func_map.get(rf.running_type, "SUM")
                alias = rf.output_field_name or f"Running{rf.running_type}_{rf.field_name}"
                extras.append(f"{func}(`{rf.field_name}`) OVER ({window}) AS `{alias}`")
            extra_str = ", ".join(extras)
            return f"SELECT *, {extra_str} FROM {inp}", warnings

        if isinstance(node, PythonToolNode):
            inp = self._get_single_input(input_ctes)
            warnings.append(f"PythonTool (node {node.node_id}) cannot be converted to SQL")
            return f"SELECT * FROM {inp} /* PythonTool: manual conversion required */", warnings

        if isinstance(node, DownloadNode):
            inp = self._get_single_input(input_ctes)
            warnings.append(f"DownloadTool (node {node.node_id}) cannot be converted to SQL")
            return f"SELECT * FROM {inp} /* DownloadTool: manual conversion required */", warnings

        if isinstance(node, RunCommandNode):
            inp = self._get_single_input(input_ctes)
            warnings.append(f"RunCommand (node {node.node_id}) cannot be converted to SQL")
            return f"SELECT * FROM {inp} /* RunCommand: not supported in SQL */", warnings

        if isinstance(node, ImputationNode):
            inp = self._get_single_input(input_ctes)
            fill_parts = []
            for fld in node.fields:
                if node.method == "custom" and node.custom_value is not None:
                    fill_parts.append(f"COALESCE(`{fld}`, '{node.custom_value}') AS `{fld}`")
                elif node.method in ("mean", "avg"):
                    fill_parts.append(f"COALESCE(`{fld}`, (SELECT AVG(`{fld}`) FROM {inp})) AS `{fld}`")
                elif node.method == "median":
                    fill_parts.append(f"COALESCE(`{fld}`, (SELECT PERCENTILE(`{fld}`, 0.5) FROM {inp})) AS `{fld}`")
                elif node.method == "mode":
                    fill_parts.append(
                        f"COALESCE(`{fld}`, (SELECT `{fld}` FROM {inp} GROUP BY `{fld}` ORDER BY COUNT(*) DESC LIMIT 1)) AS `{fld}`"
                    )
                else:
                    fill_parts.append(f"COALESCE(`{fld}`, '') AS `{fld}`")
            sel = ", ".join(["*", *fill_parts])
            return f"SELECT {sel} FROM {inp}", warnings

        if isinstance(node, XMLParseNode):
            inp = self._get_single_input(input_ctes)
            if node.xpath_expressions:
                extras = [
                    f"XPATH_STRING(`{node.input_field}`, '{xpath}') AS `{name}`"
                    for xpath, name in node.xpath_expressions
                ]
                extra_str = ", ".join(extras)
                warnings.append(f"XMLParse (node {node.node_id}): verify XPATH_STRING availability in Spark SQL")
                return f"SELECT *, {extra_str} FROM {inp}", warnings
            return f"SELECT * FROM {inp} /* XMLParse: no XPath expressions configured */", warnings

        if isinstance(node, TileNode):
            order = f"`{node.order_field}`" if node.order_field else f"`{node.tile_field}`" if node.tile_field else "1"
            if node.group_fields:
                partition = ", ".join(f"`{gf}`" for gf in node.group_fields)
                window = f"PARTITION BY {partition} ORDER BY {order}"
            else:
                window = f"ORDER BY {order}"
            return (
                f"SELECT *, NTILE({node.tile_count}) OVER ({window}) AS `{node.output_field}` FROM {self._get_single_input(input_ctes)}",
                warnings,
            )

        if isinstance(node, WeightedAverageNode):
            inp = self._get_single_input(input_ctes)
            agg = f"SUM(`{node.value_field}` * `{node.weight_field}`) / SUM(`{node.weight_field}`) AS `{node.output_field}`"
            if node.group_fields:
                gb = ", ".join(f"`{gf}`" for gf in node.group_fields)
                return f"SELECT {gb}, {agg} FROM {inp} GROUP BY {gb}", warnings
            return f"SELECT {agg} FROM {inp}", warnings

        if isinstance(node, DynamicInputNode):
            connection_hint = node.template_connection or node.file_path_pattern or "unknown"
            warnings.append(
                f"DynamicInput (node {node.node_id}): cannot auto-convert to static SQL — use PySpark output"
            )
            body = (
                f"-- TODO: DynamicInput (ModifySQL) cannot be represented as static SQL.\n"
                f"-- This tool executes parameterized SQL once per row of an input DataFrame,\n"
                f"-- substituting row values into a SQL template at runtime.\n"
                f"-- Original source: {connection_hint}\n"
                f"-- RECOMMENDATION: Use the PySpark output format for this workflow.\n"
                f"-- If SQL is required, implement the parameterized loop manually.\n"
                f"SELECT NULL AS _dynamicinput_placeholder  -- replace with manual implementation"
            )
            return body, warnings

        if isinstance(node, DynamicOutputNode):
            inp = self._get_single_input(input_ctes)
            warnings.append(f"DynamicOutput (node {node.node_id}): write operations need manual SQL conversion")
            return f"SELECT * FROM {inp} /* DynamicOutput: write operation - manual conversion needed */", warnings

        if isinstance(node, WorkflowControlNode):
            inp = self._get_single_input(input_ctes) if input_ctes else "MISSING"
            return f"SELECT * FROM {inp} /* {node.original_tool_type}: no SQL equivalent */", warnings

        if isinstance(node, MacroIONode):
            if node.direction == "input":
                return f"SELECT '{node.default_value}' AS `{node.field_name}` /* MacroInput */", warnings
            inp = self._get_single_input(input_ctes) if input_ctes else "MISSING"
            return f"SELECT * FROM {inp} /* MacroOutput */", warnings

        if isinstance(node, FieldSummaryNode):
            inp = self._get_single_input(input_ctes)
            return f"SELECT * FROM {inp} /* FieldSummary: use DESCRIBE {inp} */", warnings

        if isinstance(node, WidgetNode):
            return f"SELECT '{node.default_value}' AS `{node.field_name}` /* Widget: {node.widget_type} */", warnings

        if isinstance(node, CloudStorageNode):
            if node.provider == "s3":
                prefix = "s3://"
            elif node.provider == "azure":
                prefix = "abfss://"
            else:
                prefix = ""
            full_path = f"{prefix}{node.bucket_or_container}/{node.path}" if node.bucket_or_container else node.path
            fmt = node.file_format or "csv"
            if node.direction == "input":
                return f"SELECT * FROM {fmt}.`{full_path}`", warnings
            inp = self._get_single_input(input_ctes)
            return f"SELECT * FROM {inp} /* CloudStorage output: {full_path} */", warnings

        if isinstance(node, ChartNode):
            inp = self._get_single_input(input_ctes)
            return f"SELECT * FROM {inp} /* Chart: {node.chart_type or 'auto'} */", warnings

        if isinstance(node, ReportNode):
            inp = self._get_single_input(input_ctes)
            return f"SELECT * FROM {inp} /* Report: {node.report_type} */", warnings

        if isinstance(node, EmailOutputNode):
            inp = self._get_single_input(input_ctes)
            warnings.append(f"EmailOutput (node {node.node_id}): not convertible to SQL")
            return f"SELECT * FROM {inp} /* EmailOutput: manual conversion needed */", warnings

        # -- Spatial nodes ------------------------------------------------------

        if isinstance(node, BufferNode):
            inp = self._get_single_input(input_ctes)
            warnings.append(f"Buffer (node {node.node_id}): requires Databricks spatial functions (e.g. Mosaic)")
            return (
                f"SELECT *, st_buffer(`{node.input_field}`, {node.buffer_distance}) "
                f"AS `{node.input_field}_buffer` FROM {inp}"
            ), warnings

        if isinstance(node, SpatialMatchNode):
            target = input_ctes.get("Target", input_ctes.get("Input", "MISSING_TARGET"))
            universe = input_ctes.get("Universe", input_ctes.get("Right", input_ctes.get("Source", "MISSING_UNIVERSE")))
            warnings.append(f"SpatialMatch (node {node.node_id}): requires Databricks spatial functions (e.g. Mosaic)")
            return (
                f"SELECT * FROM {target} JOIN {universe} "
                f"ON st_intersects({target}.`{node.spatial_field_target}`, {universe}.`{node.spatial_field_universe}`)"
            ), warnings

        if isinstance(node, CreatePointsNode):
            inp = self._get_single_input(input_ctes)
            return (
                f"SELECT *, struct(`{node.lat_field}`, `{node.lon_field}`) AS `{node.output_field}` FROM {inp}"
            ), warnings

        if isinstance(node, DistanceNode):
            inp = self._get_single_input(input_ctes)
            warnings.append(f"Distance (node {node.node_id}): requires Databricks spatial functions (e.g. Mosaic)")
            return (
                f"SELECT *, st_distance(`{node.source_field}`, `{node.target_field}`) "
                f"AS `{node.output_field}` FROM {inp}"
            ), warnings

        if isinstance(node, FindNearestNode):
            target = input_ctes.get("Target", input_ctes.get("Input", "MISSING_TARGET"))
            universe = input_ctes.get("Universe", input_ctes.get("Right", input_ctes.get("Source", "MISSING_UNIVERSE")))
            warnings.append(
                f"FindNearest (node {node.node_id}): requires Databricks spatial functions; review window logic"
            )
            return (
                f"SELECT t.*, u.*, st_distance(t.`{node.target_field}`, u.`{node.universe_field}`) "
                f"AS `{node.output_distance_field}` "
                f"FROM {target} t JOIN {universe} u "
                f"QUALIFY ROW_NUMBER() OVER (PARTITION BY t.`{node.target_field}` "
                f"ORDER BY st_distance(t.`{node.target_field}`, u.`{node.universe_field}`)) <= {node.max_matches}"
            ), warnings

        if isinstance(node, GeocoderNode):
            inp = self._get_single_input(input_ctes)
            warnings.append(f"Geocoder (node {node.node_id}): geocoding requires an external API UDF in Databricks")
            return (f"SELECT * FROM {inp} /* Geocoding requires external API UDF */"), warnings

        if isinstance(node, TradeAreaNode):
            inp = self._get_single_input(input_ctes)
            warnings.append(f"TradeArea (node {node.node_id}): requires Databricks spatial functions (e.g. Mosaic)")
            return (
                f"SELECT *, st_buffer(`{node.input_field}`, {node.radius}) AS `{node.output_field}` FROM {inp}"
            ), warnings

        if isinstance(node, MakeGridNode):
            inp = self._get_single_input(input_ctes)
            warnings.append(f"MakeGrid (node {node.node_id}): requires H3 or Mosaic grid functions in Databricks")
            return (f"SELECT * FROM {inp} /* Grid: use h3_polyfill or Mosaic grid_tessellate */"), warnings

        # -- Predictive / ML tools ------------------------------------------
        if isinstance(node, PredictiveModelNode):
            tool = node.model_type or node.original_tool_type
            warnings.append(f"{tool} (node {node.node_id}): no SQL equivalent for ML tools")
            return f"-- {tool}: requires manual conversion to MLlib / pandas UDF", warnings

        if isinstance(node, UnsupportedNode):
            inp = self._get_single_input(input_ctes)
            reason = node.unsupported_reason or "No auto-conversion"
            warnings.append(f"Unsupported node {node.node_id}: {reason}")
            return f"SELECT * FROM {inp} /* UNSUPPORTED: {node.original_tool_type} - {reason} */", warnings

        # Fallback
        inp = self._get_single_input(input_ctes)
        warnings.append(f"No SQL generator for {type(node).__name__} (node {node.node_id})")
        return f"SELECT * FROM {inp} /* TODO: {type(node).__name__} */", warnings

    def _sql_ReadNode(self, node: ReadNode) -> str:
        if node.source_type == "dataverse":
            table = node.table_name or "dataverse_table"
            note = (
                f"/* TODO: Dataverse table '{table}' — replace with UC table after "
                f"Power Platform export / Fivetran / OData ingest */"
            )
            return f"SELECT * FROM {table} {note}"
        if node.source_type == "database" and node.table_name:
            return f"SELECT * FROM {node.table_name}"
        if node.source_type == "database" and node.query:
            normalized_query, _ = normalize_sql_for_spark(node.query)
            return f"({normalized_query})"
        fmt = node.file_format.lower() if node.file_format else "csv"
        path = node.file_path or "UNKNOWN_PATH"
        return f"SELECT * FROM {fmt}.`{path}`"
