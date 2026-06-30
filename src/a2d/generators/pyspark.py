"""PySpark notebook code generator.

Walks a :class:`~a2d.ir.graph.WorkflowDAG` in topological order and emits a
Databricks notebook with ``# COMMAND ----------`` cell separators.
"""

from __future__ import annotations

import logging
import re

# Pre-compiled patterns used in hot paths (per-node handlers)
_NUMERIC_LITERAL_RE = re.compile(r"^-?\d+(\.\d+)?$")
_PASSTHROUGH_RE = re.compile(r"^(df_\d+) = (df_\d+)$")
_IMPLICIT_FIELD_RE = re.compile(r'((?:ELSE)?IF)\s+"([^"]*)"(\s+THEN)')

from a2d.config import ConversionConfig
from a2d.expressions.base_translator import BaseTranslationError
from a2d.expressions.translator import PySparkTranslator
from a2d.generators.base import CodeGenerator, GeneratedFile, GeneratedOutput, NodeCodeResult
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
    DirectoryNode,
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

logger = logging.getLogger("a2d.generators.pyspark")

# Matches ISO date strings used as DynamicInput SQL placeholders, e.g. "2023-01-01"
_ISO_DATE_PLACEHOLDER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# PySpark Generator
# ---------------------------------------------------------------------------


class PySparkGenerator(CodeGenerator):
    """Generate a Databricks PySpark notebook from a WorkflowDAG."""

    def __init__(self, config: ConversionConfig) -> None:
        super().__init__(config)
        self._translator = PySparkTranslator()

    @staticmethod
    def _esc(s: str) -> str:
        """Escape a string for safe embedding inside a double-quoted Python string literal."""
        return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")

    # -- Public API ---------------------------------------------------------

    def generate(self, dag: WorkflowDAG, workflow_name: str = "workflow") -> GeneratedOutput:
        ordered_nodes = dag.topological_order()
        warnings: list[str] = []
        all_imports: set[str] = {
            "from pyspark.sql import functions as F",
            "from pyspark.sql import Window",
        }
        var_map: dict[int, dict[str, str]] = {}  # node_id -> {anchor: var_name}
        cells: list[str] = []
        node_count = 0
        unsupported_count = 0

        # Track ReadNodes whose spark.sql(...) expression is inlined into the
        # single downstream cell rather than materialised as a named variable.
        # pending_inline_note maps successor_node_id -> comment note to prepend.
        pending_inline_note: dict[int, str] = {}

        for node in ordered_nodes:
            if isinstance(node, CommentNode):
                # Canvas comments become code comments, no variable output
                if node.comment_text:
                    comment_lines = node.comment_text.splitlines()
                    cells.append("\n".join(f"# {line}" for line in comment_lines))
                continue

            # Inline single-use DB ReadNodes: if this node is a plain DB query
            # that feeds exactly one downstream step, skip emitting it as its own
            # cell. Store the spark.sql(...) expression as the "variable" in
            # var_map so the downstream generator picks it up directly.
            if isinstance(node, ReadNode) and node.source_type == "database" and node.query:
                successors = dag.get_successors(node.node_id)
                if len(successors) == 1:
                    normalized_query, _sql_warns = normalize_sql_for_spark(node.query)
                    safe_query = normalized_query.replace('"""', '""\\"')
                    sql_expr = f'spark.sql("""{safe_query}""")'
                    var_map[node.node_id] = {"Output": sql_expr}
                    conn_hint = f" — {node.connection_string}" if node.connection_string else ""
                    todo_hint = " — TODO: map to Unity Catalog" if node.connection_string else ""
                    pending_inline_note[successors[0].node_id] = (
                        f"  [input: Step {node.node_id} (Input){conn_hint}{todo_hint}]"
                    )
                    node_count += 1
                    continue  # no cell emitted for this node

            input_vars = self._resolve_input_vars(node.node_id, dag, var_map)
            result = self._generate_node_code(node, input_vars, dag=dag)

            if result.imports:
                all_imports.update(result.imports)
            if result.warnings:
                warnings.extend(result.warnings)
            if isinstance(node, UnsupportedNode):
                unsupported_count += 1

            # Register output variables
            var_map[node.node_id] = result.output_vars

            # Eliminate pure passthrough cells: if the only generated line is a simple
            # variable alias "df_N = df_M" (no method calls), redirect var_map to the
            # source variable so downstream nodes skip the indirection entirely.
            out_var = result.output_vars.get("Output", "")
            if out_var and len(result.code_lines) == 1 and not node.annotation:
                _m = _PASSTHROUGH_RE.match(result.code_lines[0])
                if _m and _m.group(1) == out_var:
                    var_map[node.node_id] = {"Output": _m.group(2)}
                    node_count += 1
                    continue  # nothing to emit for this cell

            # Fan-out caching: if this node feeds 2+ downstream nodes, cache its output
            # so Spark doesn't recompute the same DataFrame for each consumer.
            out_var = result.output_vars.get("Output")
            successors = dag.get_successors(node.node_id)
            if out_var and len(successors) >= 2:
                result.code_lines.append(
                    f"{out_var}.cache()  # fan-out node: result reused by multiple downstream steps"
                )

            # Build cell content
            annotation = ""
            if self.config.include_comments and node.annotation:
                # Prefix every line with # to avoid SyntaxError on multi-line annotations
                annotation_lines = node.annotation.splitlines()
                annotation = "\n".join(f"# {line}" for line in annotation_lines) + "\n"

            # Step header — always emitted as navigation metadata.
            # For fan-out DB ReadNodes, list the downstream steps so the
            # Alteryx→Databricks mapping remains visible in both directions.
            step_label = node.original_tool_type or type(node).__name__
            if isinstance(node, ReadNode) and node.source_type == "database" and len(successors) > 1:
                consumer_ids = ", ".join(str(s.node_id) for s in successors)
                step_label += f"  (shared by Steps {consumer_ids})"
            step_comment = f"# Step {node.node_id}: {step_label}"

            # If an upstream ReadNode was inlined into this cell, append its note.
            if node.node_id in pending_inline_note:
                step_comment += pending_inline_note[node.node_id]

            comment = step_comment + "\n"
            cell = annotation + comment + "\n".join(result.code_lines)
            cells.append(cell)
            node_count += 1

        # Build notebook content
        # Update metadata with stats for header generation
        self.metadata["stats"] = {
            "total_nodes": node_count,
            "supported_nodes": node_count - unsupported_count,
            "unsupported_nodes": unsupported_count,
            "warnings": len(warnings),
        }

        header_lines = self._build_header_lines(workflow_name, "#")
        header_cell = "\n".join(header_lines)

        import_cell = "\n".join(sorted(all_imports))
        separator = "\n\n# COMMAND ----------\n\n"
        notebook_body = separator.join([header_cell, import_cell, *cells])
        notebook_content = "# Databricks notebook source\n" + separator + notebook_body + "\n"

        # Append footer
        footer_lines = self._build_footer_lines(notebook_content, "#")
        notebook_content += separator + "\n".join(footer_lines) + "\n"

        # Validate generated Python syntax
        syntax_errors = self._validate_python_syntax(notebook_content, f"{workflow_name}.py")
        if syntax_errors:
            warnings.extend(syntax_errors)

        files = [
            GeneratedFile(
                filename=f"{workflow_name}.py",
                content=notebook_content,
                file_type="python",
            )
        ]

        stats = {
            "total_nodes": node_count,
            "supported_nodes": node_count - unsupported_count,
            "unsupported_nodes": unsupported_count,
            "warnings": len(warnings),
        }

        return GeneratedOutput(files=files, warnings=warnings, stats=stats)

    # -- Input resolution ---------------------------------------------------

    def _resolve_input_vars(self, node_id: int, dag: WorkflowDAG, var_map: dict[int, dict[str, str]]) -> dict[str, str]:
        """Determine input DataFrame variable names from predecessors.

        Returns a dict mapping destination anchor name -> variable name.
        For example ``{"Input": "df_1", "Left": "df_2", "Right": "df_3"}``.
        """
        result: dict[str, str] = {}
        preds = dag.get_predecessors(node_id)
        for pred in preds:
            edge_info = dag.get_edge_info(pred.node_id, node_id)
            origin_anchor = edge_info.origin_anchor
            dest_anchor = edge_info.destination_anchor

            pred_vars = var_map.get(pred.node_id, {})
            # Try to match origin anchor to a specific output variable
            if origin_anchor in pred_vars:
                var_name = pred_vars[origin_anchor]
            elif "Output" in pred_vars:
                var_name = pred_vars["Output"]
            elif pred_vars:
                # Take the first available output
                var_name = next(iter(pred_vars.values()))
            else:
                var_name = f"df_{pred.node_id}"

            # Deduplicate: if two connections share the same dest_anchor (e.g. Union
            # uses "Input" for every incoming edge), suffix with a counter so all
            # inputs are preserved in the dict.
            if dest_anchor in result:
                counter = 2
                while f"{dest_anchor}_{counter}" in result:
                    counter += 1
                dest_anchor = f"{dest_anchor}_{counter}"
            result[dest_anchor] = var_name
        return result

    # -- Node dispatch ------------------------------------------------------

    def _generate_node_code(
        self, node: IRNode, input_vars: dict[str, str], dag: WorkflowDAG | None = None
    ) -> NodeCodeResult:
        """Generate PySpark code for a single IR node."""
        type_name = type(node).__name__
        method_name = f"_generate_{type_name}"
        method = getattr(self, method_name, None)
        if method is not None:
            # Pass dag to methods that support dead-branch pruning
            if type_name in ("FilterNode", "JoinNode") and dag is not None:
                return method(node, input_vars, dag=dag)
            return method(node, input_vars)
        # Fallback for unknown node types
        return self._generate_fallback(node, input_vars)

    def _generate_fallback(self, node: IRNode, input_vars: dict[str, str]) -> NodeCodeResult:
        return self._unsupported_passthrough(node, input_vars)

    # -- IO nodes -----------------------------------------------------------

    def _generate_ReadNode(self, node: ReadNode, input_vars: dict[str, str]) -> NodeCodeResult:
        out_var = f"df_{node.node_id}"
        raw_fmt = node.file_format  # keep original format string for format-specific branches
        fmt = self._map_file_format(raw_fmt)
        path = node.file_path or node.table_name or "UNKNOWN_PATH"
        warnings: list[str] = []

        options: list[str] = []
        if fmt == "csv":
            options.append(f'"header", "{str(node.has_header).lower()}"')
            if node.delimiter and node.delimiter != ",":
                options.append(f'"delimiter", "{node.delimiter}"')
            if node.encoding and node.encoding != "utf-8":
                options.append(f'"encoding", "{node.encoding}"')

        if node.source_type == "dataverse":
            table = node.table_name or "<dataverse_table>"
            lines = [
                "# TODO: Microsoft Dataverse input — no native Databricks reader.",
                f"# Dataverse table (LogicalName): {table}",
            ]
            if node.connection_string:
                lines.append(f"# Original connection: {node.connection_string}")
            if node.query:
                safe_query = node.query.replace('"""', '""\\"')
                lines.append(f"# Original OData query: {safe_query}")
            lines += [
                "# Suggested replacements (pick one):",
                "#   1. Export Dataverse → ADLS via Power Platform, then spark.read.format('parquet').load('abfss://...')",
                "#   2. Ingest with Fivetran / Airbyte / Hightouch Dataverse connector into a UC table",
                "#      then: spark.table('catalog.schema.{table}')".replace("{table}", table),
                "#   3. Custom OData ingest via requests + spark.createDataFrame()",
                f'{out_var} = spark.createDataFrame([], "id STRING")  # PLACEHOLDER — replace with Dataverse load',
            ]
            warnings.append(f"Input node {node.node_id}: Dataverse table '{table}' requires manual ingest setup")
            if node.record_limit is not None:
                lines.append(f"{out_var} = {out_var}.limit({node.record_limit})")
            return NodeCodeResult(
                code_lines=lines,
                output_vars={"Output": out_var},
                warnings=warnings,
            )

        if node.source_type == "database" and node.query:
            lines = []
            if node.connection_string:
                lines.append(f"# Source database: {node.connection_string}")
                lines.append("# TODO: Replace the connection below with your Unity Catalog equivalent. Options:")
                lines.append(
                    '#   spark.table("catalog.schema.table_name")                       # UC managed/external table'
                )
                lines.append(
                    '#   spark.sql("SELECT ... FROM catalog.schema.table_name")         # keep SQL, update table ref'
                )
                lines.append(
                    '#   spark.table("federated_catalog.schema.table_name")             # Lakehouse Federation (preferred for legacy DBs:'
                )
                lines.append(
                    "#                                                                  #   CREATE FOREIGN CATALOG federated_catalog USING CONNECTION ...;"
                )
                lines.append(
                    "#                                                                  #   docs: https://docs.databricks.com/aws/en/query-federation/)"
                )
                lines.append(
                    '#   spark.read.format("jdbc").option("url","jdbc:...").option("dbtable","schema.table").load()  # JDBC fallback (no UC governance)'
                )
                warnings.append(
                    f"Input node {node.node_id}: database connection '{node.connection_string}' needs manual mapping"
                )
            normalized_query, _sql_warns = normalize_sql_for_spark(node.query)
            safe_query = normalized_query.replace('"""', '""\\"')
            lines.append(f'{out_var} = spark.sql("""{safe_query}""")')
        elif node.source_type == "database" and node.table_name:
            lines = [f'{out_var} = spark.table("{node.table_name}")']
        elif raw_fmt in ("xlsx", "xls"):
            # Excel files require a dedicated reader not bundled with Databricks.
            # Extract sheet name if encoded in path as "file.xlsx|||`SheetName$`"
            xlsx_path = path
            sheet_hint = ""
            if "|||" in path:
                xlsx_path, sheet_hint = path.split("|||", 1)
            lines = [
                "# TODO: manual conversion required — Excel files need a dedicated reader.",
                f"# Original path: {xlsx_path}",
            ]
            if sheet_hint:
                lines.append(f"# Sheet: {sheet_hint.strip()}")
            lines += [
                "# Options:",
                "#   1. Use pandas: import pandas as pd; df = pd.read_excel(path, sheet_name='...')",
                "#      then: df_{node_id} = spark.createDataFrame(df)".replace("{node_id}", str(node.node_id)),
                "#   2. Install com.crealytics:spark-excel and use spark.read.format('excel')",
                f"{out_var} = None  # PLACEHOLDER — replace with Excel read logic",
            ]
            warnings.append(
                f"Input node {node.node_id}: Excel file requires manual conversion (no built-in Excel reader)"
            )
        else:
            option_chain = ""
            if options:
                opt_parts = ", ".join(f".option({o})" for o in options)
                option_chain = opt_parts
            # Escape backslashes and quotes so the path embeds safely in a Python string literal
            escaped_path = self._esc(path)
            # Warn about Windows UNC paths that are inaccessible in Databricks
            if path.startswith("\\\\") or (path.startswith("\\") and len(path) > 1 and path[1] != "\\"):
                lines = [
                    "# WARNING: local/network path detected — not accessible from Databricks.",
                    "# Upload the file to DBFS or a Unity Catalog Volume and update the path below.",
                    f"# Original path: {path}",
                    f'{out_var} = spark.read.format("{fmt}"){option_chain}.load("{escaped_path}")',
                ]
                warnings.append(
                    f"Input node {node.node_id}: path '{path}' is a local/UNC path — needs migration to cloud storage"
                )
            else:
                lines = [f'{out_var} = spark.read.format("{fmt}"){option_chain}.load("{escaped_path}")']

        if node.record_limit is not None:
            lines.append(f"{out_var} = {out_var}.limit({node.record_limit})")

        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=warnings,
        )

    def _generate_WriteNode(self, node: WriteNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        fmt = self._map_file_format(node.file_format).strip('"').strip("'")
        mode = node.write_mode or "overwrite"
        warnings: list[str] = []

        # Build .partitionBy() clause if partition fields specified
        partition_clause = ""
        if node.partition_fields:
            pf = ", ".join(f'"{f}"' for f in node.partition_fields)
            partition_clause = f".partitionBy({pf})"

        # Build .option("compression", ...) clause if specified
        compression_clause = ""
        if node.compression:
            compression_clause = f'.option("compression", "{node.compression}")'

        if node.destination_type == "database" and node.table_name:
            lines = [f'{inp}.write.mode("{mode}"){partition_clause}.saveAsTable("{self._esc(node.table_name)}")']
        else:
            path = node.file_path or "UNKNOWN_PATH"
            # Unsupported output formats get a comment + Delta fallback
            if fmt in ("hyper", "yxdb", "unknown"):
                catalog = self.config.catalog_name
                schema = self.config.schema_name
                table = f"output_{node.node_id}"
                lines = [
                    f"# Original output: {path}",
                    f"# Format '{fmt}' is not natively supported in Databricks.",
                    f"# Writing as Delta table instead. Export to {fmt} if needed.",
                    f'{inp}.write.mode("{mode}"){partition_clause}.saveAsTable("{catalog}.{schema}.{table}")',
                ]
                warnings.append(f"Output node {node.node_id}: '{fmt}' format replaced with Delta table")
            elif node.file_format in ("xlsx", "xls"):
                # Excel write is not natively supported in Databricks — emit a TODO with options
                base_path = path.split("|||")[0] if "|||" in path else path
                sheet_part = path.split("|||", 1)[1].strip() if "|||" in path else ""
                sheet_hint = f" (Sheet: {sheet_part})" if sheet_part else ""
                lines = [
                    "# TODO: Excel write not supported natively in Databricks.",
                    f"# Original path: {base_path}{sheet_hint}",
                    "# Option 1 — write as CSV instead:",
                    f'# {inp}.write.format("csv").option("header", "true").mode("{mode}").save("# TODO: /Volumes/catalog/schema/volume/filename.csv")',
                    "# Option 2 — use com.crealytics.spark.excel library if installed on the cluster:",
                    f'# {inp}.write.format("com.crealytics.spark.excel").option("header", "true").option("dataAddress", "\'A1\'").mode("{mode}").save("# TODO: /Volumes/catalog/schema/volume/filename.xlsx")',
                ]
                warnings.append(f"Output node {node.node_id}: Excel write not supported — manual conversion required")
            else:
                escaped_path = self._esc(path)
                if path.startswith("\\\\") or (path.startswith("\\") and len(path) > 1 and path[1] != "\\"):
                    lines = [
                        "# WARNING: local/network path detected — not accessible from Databricks.",
                        "# Update the path below to a DBFS path or Unity Catalog Volume.",
                        f"# Original path: {path}",
                        # Hardcoded TODO target on the .save() so customers
                        # see the broken path and migrate it before running;
                        # session's compression/partition options stay so the
                        # write semantics match what the workflow specified.
                        f'{inp}.write.format("{fmt}").mode("{mode}"){compression_clause}{partition_clause}.save("# TODO: /Volumes/catalog/schema/volume/filename")  # original: {escaped_path}',
                    ]
                    warnings.append(
                        f"Output node {node.node_id}: path '{path}' is a local/UNC path — needs migration to cloud storage"
                    )
                else:
                    lines = [
                        f'{inp}.write.format("{fmt}").mode("{mode}"){compression_clause}{partition_clause}.save("{escaped_path}")'
                    ]

        return NodeCodeResult(code_lines=lines, output_vars={}, warnings=warnings)

    def _generate_LiteralDataNode(self, node: LiteralDataNode, input_vars: dict[str, str]) -> NodeCodeResult:
        out_var = f"df_{node.node_id}"

        rows_repr = repr(node.data_rows) if node.data_rows else "[]"
        schema_repr = repr(node.field_names) if node.field_names else "[]"

        lines = [f"{out_var} = spark.createDataFrame({rows_repr}, schema={schema_repr})"]
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
        )

    def _generate_BrowseNode(self, node: BrowseNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        lines = [
            "# Browse tool -- display data preview",
            f"display({inp})",
        ]
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": inp},
        )

    # -- Preparation nodes --------------------------------------------------

    def _generate_FilterNode(
        self, node: FilterNode, input_vars: dict[str, str], dag: WorkflowDAG | None = None
    ) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_true = f"df_{node.node_id}_true"
        out_false = f"df_{node.node_id}_false"
        warnings: list[str] = []

        # Determine which branches are actually wired downstream
        used_anchors = dag.get_outgoing_anchors(node.node_id) if dag is not None else {"True", "False"}
        need_true = "True" in used_anchors or "Output" in used_anchors
        need_false = "False" in used_anchors

        if not node.expression or not node.expression.strip():
            warnings.append(
                f"Filter node {node.node_id} has no expression — passing all rows to True output (no False output)"
            )
            lines = [
                f"# TODO: Filter node {node.node_id} — expression could not be extracted from workflow XML",
                f"{out_true} = {inp}",
            ]
            if need_false:
                lines.append(f"{out_false} = {inp}.limit(0)  # empty — no filter expression available")
        else:
            try:
                expr = self._translator.translate_string(node.expression)
                warnings.extend(self._translator.warnings)
            except BaseTranslationError as exc:
                # Expression could not be parsed — emit a placeholder so the notebook
                # at least loads cleanly, with a clear TODO for manual conversion.
                raw_escaped = node.expression.replace("\\", "\\\\").replace('"', '\\"')
                expr = "F.lit(True)  # PLACEHOLDER — see TODO below"
                warnings.append(f"Filter expression fallback for node {node.node_id}: {exc}")
                manual_lines = [
                    f"# TODO: manual conversion required — filter expression parse failed: {exc}",
                    f'# Original Alteryx expression: "{raw_escaped}"',
                    "# Replace the F.lit(True) placeholder below with the correct PySpark condition.",
                ]
                lines = manual_lines  # will be extended below
                if need_true and need_false:
                    lines += [
                        f"_filter_cond_{node.node_id} = {expr}",
                        f"{out_true} = {inp}.filter(_filter_cond_{node.node_id})",
                        f"{out_false} = {inp}.filter(~(_filter_cond_{node.node_id}))",
                    ]
                elif need_true:
                    lines += [f"{out_true} = {inp}  # passthrough — replace with correct filter"]
                else:
                    lines += [f"{out_false} = {inp}.limit(0)  # passthrough — replace with correct filter"]
                output_vars_local: dict[str, str] = {"Output": out_true}
                if need_true:
                    output_vars_local["True"] = out_true
                if need_false:
                    output_vars_local["False"] = out_false
                return NodeCodeResult(code_lines=lines, output_vars=output_vars_local, warnings=warnings)

            if need_true and need_false:
                # Both branches needed — use a shared condition variable
                lines = [
                    f"_filter_cond_{node.node_id} = {expr}",
                    f"{out_true} = {inp}.filter(_filter_cond_{node.node_id})",
                    f"{out_false} = {inp}.filter(~(_filter_cond_{node.node_id}))",
                ]
            elif need_true:
                lines = [f"{out_true} = {inp}.filter({expr})"]
            else:
                # Only false branch needed (rare)
                lines = [f"{out_false} = {inp}.filter(~({expr}))"]

        output_vars: dict[str, str] = {"Output": out_true}
        if need_true:
            output_vars["True"] = out_true
        if need_false:
            output_vars["False"] = out_false

        return NodeCodeResult(
            code_lines=lines,
            output_vars=output_vars,
            warnings=warnings,
        )

    def _generate_FormulaNode(self, node: FormulaNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        warnings: list[str] = []
        todo_lines: list[str] = []

        # Translate all formulas up front so we can inspect dependencies
        translated: list[tuple[str, str]] = []  # (output_field, pyspark_expr)
        for formula in node.formulas:
            try:
                fixed_expression = self._fix_implicit_field_refs(formula.expression, formula.output_field)
                expr = self._translator.translate_string(fixed_expression)
                warnings.extend(self._translator.warnings)
                # Bare numeric literal used as a column expression needs F.lit()
                if _NUMERIC_LITERAL_RE.match(expr.strip()):
                    expr = f"F.lit({expr})"
            except BaseTranslationError as exc:
                raw_escaped = formula.expression.replace("\\", "\\\\").replace('"', '\\"')
                expr = "F.lit(None)  # PLACEHOLDER"
                warnings.append(f"Formula expression fallback for '{formula.output_field}': {exc}")
                todo_lines.append(f"# TODO: manual conversion required — expression parse failed: {exc}")
                todo_lines.append(f'# Original Alteryx expression: "{raw_escaped}"')
            translated.append((formula.output_field, expr))

        lines: list[str] = todo_lines[:]

        if not translated:
            return NodeCodeResult(code_lines=lines, output_vars={"Output": inp}, warnings=warnings)

        # Detect whether any formula references a previous formula's output field.
        # If so, sequential withColumn calls are required to preserve evaluation order.
        defined_fields: list[str] = []
        has_sequential_dependency = False
        for field_name, expr in translated:
            if any(f'F.col("{prev}")' in expr for prev in defined_fields):
                has_sequential_dependency = True
                break
            defined_fields.append(field_name)

        if has_sequential_dependency:
            # Fall back to sequential withColumn calls to preserve inter-formula dependencies
            for i, (field_name, expr) in enumerate(translated):
                src = inp if i == 0 else out_var
                lines.append(f'{out_var} = {src}.withColumn("{self._esc(field_name)}", {expr})')
        else:
            # All formulas are independent — emit a single withColumns call
            entries = ",\n    ".join(f'"{self._esc(field_name)}": {expr}' for field_name, expr in translated)
            lines.append(f"{out_var} = {inp}.withColumns({{\n    {entries},\n}})")

        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=warnings,
        )

    @staticmethod
    def _fix_implicit_field_refs(expression: str, output_field: str) -> str:
        """Fix Alteryx expressions with implicit field references.

        Some Alteryx formulas use bare literal conditions in IF/ELSEIF blocks
        (e.g. ``IF "101" THEN "HELOC"``), where the field being tested is
        implicitly the output field.  This rewrites them to explicit comparisons
        (e.g. ``IF [PRODUCT_TYPE] = "101" THEN "HELOC"``).
        """
        from a2d.expressions.ast import IfExpr, Literal
        from a2d.expressions.parser import ExpressionParser

        if not expression or not expression.strip():
            return expression

        try:
            parser = ExpressionParser()
            ast = parser.parse(expression)
        except BaseTranslationError:
            return expression  # leave unparseable expressions alone

        if not isinstance(ast, IfExpr):
            return expression

        # Check if the IF or any ELSEIF condition is a bare literal
        needs_fix = isinstance(ast.condition, Literal)
        if not needs_fix:
            needs_fix = any(isinstance(cond, Literal) for cond, _ in ast.elseif_clauses)

        if not needs_fix:
            return expression

        # Rewrite bare literal conditions to [output_field] = literal
        escaped_field = output_field.replace('"', '\\"')
        result = expression
        # Use regex to find IF/ELSEIF followed by a bare string literal (not a comparison)
        result = _IMPLICIT_FIELD_RE.sub(
            rf'\1 [{escaped_field}] = "\2"\3',
            result,
        )
        return result

    def _generate_SelectNode(self, node: SelectNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"

        renames: list[tuple[str, str]] = []
        drops: list[str] = []

        for op in node.field_operations:
            if not op.selected or op.action == FieldAction.DESELECT:
                drops.append(op.field_name)
            elif op.action == FieldAction.RENAME and op.rename_to:
                renames.append((op.field_name, op.rename_to))

        # No-op Select: nothing to rename or drop — pass input through directly
        if not renames and not drops:
            return NodeCodeResult(code_lines=[], output_vars={"Output": inp})

        # Build a single chained expression: inp.withColumnsRenamed({...}).drop(...)
        # withColumnsRenamed (Spark 3.4+, DBR 14.3 LTS+) takes a dict and avoids the
        # quadratic schema-rebuild cost of a long .withColumnRenamed chain.
        chain_parts: list[str] = []
        if renames:
            rename_entries = ", ".join(f'"{old}": "{new}"' for old, new in renames)
            chain_parts.append(f"    .withColumnsRenamed({{{rename_entries}}})")
        if drops:
            drop_args = ", ".join(f'"{d}"' for d in drops)
            chain_parts.append(f"    .drop({drop_args})")
        chain_body = "\n".join(chain_parts)
        lines: list[str] = [f"{out_var} = (\n    {inp}\n{chain_body}\n)"]

        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
        )

    def _generate_SortNode(self, node: SortNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"

        sort_exprs: list[str] = []
        for sf in node.sort_fields:
            direction = "asc" if sf.ascending else "desc"
            expr = f'F.col("{sf.field_name}").{direction}'
            if sf.nulls_first is True:
                expr += "_nulls_first()"
            elif sf.nulls_first is False:
                expr += "_nulls_last()"
            else:
                expr += "()"
            sort_exprs.append(expr)

        sort_str = ", ".join(sort_exprs) if sort_exprs else ""
        lines = [f"{out_var} = {inp}.orderBy({sort_str})"]

        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
        )

    def _generate_SampleNode(self, node: SampleNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        seed_arg = f", seed={node.seed}" if node.seed is not None else ""

        if node.sample_method in ("first",) and node.n_records is not None:
            lines = [f"{out_var} = {inp}.limit({node.n_records})"]
        elif node.sample_method == "percent" and node.percentage is not None:
            frac = node.percentage / 100.0 if node.percentage > 1 else node.percentage
            lines = [f"{out_var} = {inp}.sample(fraction={frac}{seed_arg})"]
        elif node.sample_method == "random" and node.n_records is not None:
            lines = [
                f"# Random sample of {node.n_records} records",
                f"_count_{node.node_id} = {inp}.count()",
                f"_frac_{node.node_id} = ({node.n_records} * 2 / _count_{node.node_id}) if _count_{node.node_id} > 0 else 1.0",
                f"_frac_{node.node_id} = _frac_{node.node_id} if _frac_{node.node_id} <= 1.0 else 1.0",
                f"{out_var} = {inp}.sample(fraction=_frac_{node.node_id}{seed_arg}).limit({node.n_records})",
            ]
        else:
            lines = [
                f"# Sample method: {node.sample_method}",
                f"{out_var} = {inp}.limit({node.n_records or 100})",
            ]

        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
        )

    def _generate_UniqueNode(self, node: UniqueNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_unique = f"df_{node.node_id}_unique"
        out_dup = f"df_{node.node_id}_duplicate"

        keys_repr = repr(node.key_fields) if node.key_fields else "[]"

        lines = [
            f"{out_unique} = {inp}.dropDuplicates({keys_repr})",
            f"{out_dup} = {inp}.subtract({out_unique})",
        ]
        return NodeCodeResult(
            code_lines=lines,
            output_vars={
                "Unique": out_unique,
                "Duplicate": out_dup,
                "Output": out_unique,
            },
        )

    def _generate_RecordIDNode(self, node: RecordIDNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        start = node.starting_value

        lines = [f'{out_var} = {inp}.withColumn("{node.output_field}", F.monotonically_increasing_id() + {start})']
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
        )

    def _generate_MultiRowFormulaNode(self, node: MultiRowFormulaNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        warnings: list[str] = []

        # Build window spec
        # NOTE: monotonically_increasing_id() is non-deterministic — replace with a
        # deterministic column (e.g. a timestamp or sequence key) for reproducible results.
        if node.group_fields:
            partition = ", ".join(f'"{gf}"' for gf in node.group_fields)
            window_def = f"Window.partitionBy({partition}).orderBy(F.monotonically_increasing_id())"
        else:
            window_def = "Window.orderBy(F.monotonically_increasing_id())"
        warnings.append(
            f"MultiRowFormula node {node.node_id}: window ordered by monotonically_increasing_id() "
            "which is non-deterministic. Replace with a deterministic sort column for reproducible results."
        )

        try:
            expr = self._translator.translate_string(node.expression)
            warnings.extend(self._translator.warnings)
        except BaseTranslationError as exc:
            safe = node.expression.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
            expr = f'F.expr("{safe}")'
            warnings.append(f"MultiRowFormula expression fallback: {exc}")

        # Replace the placeholder 'window' with actual window variable
        expr = expr.replace(".over(window)", f".over(_window_{node.node_id})")

        lines = [
            f"_window_{node.node_id} = {window_def}",
            f'{out_var} = {inp}.withColumn("{node.output_field}", {expr})',
        ]
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=warnings,
        )

    def _generate_MultiFieldFormulaNode(
        self, node: MultiFieldFormulaNode, input_vars: dict[str, str]
    ) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        warnings: list[str] = []
        todo_lines: list[str] = []
        field_exprs: list[tuple[str, str]] = []  # (output_name, expr)

        for fld in node.fields:
            try:
                expr_str = node.expression.replace("[_CurrentField_]", f"[{fld}]")
                expr = self._translator.translate_string(expr_str)
                warnings.extend(self._translator.warnings)
                # Bare numeric literal used as a column expression needs F.lit()
                if _NUMERIC_LITERAL_RE.match(expr.strip()):
                    expr = f"F.lit({expr})"
            except BaseTranslationError as exc:
                expr = f'F.col("{fld}")  # PLACEHOLDER'
                warnings.append(f"MultiFieldFormula fallback for field '{fld}': {exc}")
                todo_lines.append(f'# TODO: MultiFieldFormula fallback for "{fld}": {exc}')

            output_name = f"{fld}_out" if node.copy_output else fld
            field_exprs.append((output_name, expr))

        lines: list[str] = todo_lines[:]
        if field_exprs:
            entries = ",\n    ".join(f'"{name}": {expr}' for name, expr in field_exprs)
            lines.append(f"{out_var} = {inp}.withColumns({{\n    {entries},\n}})")
        else:
            lines.append(f"{out_var} = {inp}")

        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=warnings,
        )

    def _generate_DataCleansingNode(self, node: DataCleansingNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"

        # Build a composed expression per field, then emit a single withColumns()
        field_exprs: dict[str, str] = {}
        null_fill: dict[str, str] = {}

        for fld in node.fields:
            expr = f'F.col("{fld}")'
            if node.trim_whitespace:
                expr = f"F.trim({expr})"
            if node.modify_case == "upper":
                expr = f"F.upper({expr})"
            elif node.modify_case == "lower":
                expr = f"F.lower({expr})"
            elif node.modify_case == "title":
                expr = f"F.initcap({expr})"
            if node.remove_tabs:
                expr = f'F.regexp_replace({expr}, "\\\\t", "")'
            if node.remove_line_breaks:
                expr = f'F.regexp_replace({expr}, "[\\\\r\\\\n]+", "")'
            if node.remove_duplicate_whitespace:
                expr = f'F.regexp_replace({expr}, "\\\\s+", " ")'

            # Only add to withColumns if there are actual transformations
            if expr != f'F.col("{fld}")':
                field_exprs[fld] = expr

            if node.remove_null:
                null_fill[fld] = f'"{node.replace_nulls_with}"' if node.replace_nulls_with is not None else '""'

        lines: list[str] = []

        if field_exprs:
            entries = ", ".join(f'"{fld}": {expr}' for fld, expr in field_exprs.items())
            lines.append(f"{out_var} = {inp}.withColumns({{{entries}}})")
        else:
            lines.append(f"{out_var} = {inp}")

        if null_fill:
            fill_dict = ", ".join(f'"{fld}": {val}' for fld, val in null_fill.items())
            lines.append(f"{out_var} = {out_var}.na.fill({{{fill_dict}}})")

        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
        )

    def _generate_AutoFieldNode(self, node: AutoFieldNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        # AutoField is a no-op in Spark — pass input through directly
        return NodeCodeResult(
            code_lines=["# AutoField: automatic type sizing (no-op in Spark — passthrough)"],
            output_vars={"Output": inp},
        )

    def _generate_GenerateRowsNode(self, node: GenerateRowsNode, input_vars: dict[str, str]) -> NodeCodeResult:
        out_var = f"df_{node.node_id}"
        warnings: list[str] = []
        lines = []

        # Try to parse init/condition/loop as simple counter pattern
        # Common pattern: i=1, i<=N, i=i+1
        init_expr = node.init_expression.strip()
        cond_expr = node.condition_expression.strip()
        loop_expr = node.loop_expression.strip()

        lines.append(f"# GenerateRows: init='{init_expr}', cond='{cond_expr}', loop='{loop_expr}'")

        # Attempt to detect simple range pattern
        range_match = re.search(r"(\w+)\s*<=?\s*(\d+)", cond_expr)
        init_match = re.search(r"(\w+)\s*=\s*(\d+)", init_expr)

        if init_match and range_match:
            start_val = int(init_match.group(2))
            end_val = int(range_match.group(2))
            if "<=" in cond_expr:
                end_val += 1
            output_field = node.output_field or init_match.group(1)
            lines.append(f'{out_var} = spark.range({start_val}, {end_val}).withColumnRenamed("id", "{output_field}")')
        else:
            # Fallback: generate a UDF-based approach with manual guidance
            output_field = node.output_field or "GeneratedRow"
            lines.append("# Complex row generation - using spark.range with expression application")
            lines.append(f'{out_var} = spark.range(0, 1000).withColumnRenamed("id", "{output_field}")')
            if cond_expr:
                try:
                    expr = self._translator.translate_string(
                        cond_expr.replace(node.output_field or "i", f"[{output_field}]")
                    )
                    lines.append(f"{out_var} = {out_var}.filter({expr})")
                except BaseTranslationError:
                    lines.append(f"# Apply condition filter: {cond_expr}")
                    warnings.append(f"GenerateRows (node {node.node_id}): complex condition may need manual adjustment")
            if loop_expr and loop_expr != f"{output_field}+1" and loop_expr != f"{output_field} + 1":
                warnings.append(
                    f"GenerateRows (node {node.node_id}): loop expression '{loop_expr}' may need manual adjustment"
                )

        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=warnings,
        )

    # -- Join nodes ---------------------------------------------------------

    def _generate_JoinNode(
        self, node: JoinNode, input_vars: dict[str, str], dag: WorkflowDAG | None = None
    ) -> NodeCodeResult:
        left_var = input_vars.get("Left", input_vars.get("Input", "MISSING_LEFT"))
        right_var = input_vars.get("Right", "MISSING_RIGHT")
        out_join = f"df_{node.node_id}_join"
        out_left = f"df_{node.node_id}_left"
        out_right = f"df_{node.node_id}_right"

        join_type = node.join_type or "inner"

        no_keys_warning = False
        if node.join_keys:
            key_pairs = [f'{left_var}["{jk.left_field}"] == {right_var}["{jk.right_field}"]' for jk in node.join_keys]
            condition = " & ".join(f"({kp})" for kp in key_pairs)
            if len(key_pairs) == 1:
                condition = key_pairs[0]
        else:
            condition = "F.lit(True)"
            no_keys_warning = True

        # Determine which outputs are actually wired downstream
        used_anchors = dag.get_outgoing_anchors(node.node_id) if dag is not None else {"Join", "Left", "Right"}
        need_join = "Join" in used_anchors or "Output" in used_anchors
        need_left = "Left" in used_anchors
        need_right = "Right" in used_anchors

        lines: list[str] = []
        output_vars: dict[str, str] = {}
        warnings: list[str] = []
        if no_keys_warning:
            lines.append(
                f"# TODO: Join node {node.node_id} has no join keys — replace F.lit(True) with the correct condition"
            )
            warnings.append(f"Join node {node.node_id}: no join keys found — manual condition required")

        # Detect broadcast candidates: small lookup inputs (LiteralData or single-use ReadNodes)
        broadcast_side: str | None = None  # "left" or "right"
        if dag is not None:
            from a2d.ir.nodes import LiteralDataNode

            predecessors = dag.get_predecessors(node.node_id)
            for pred in predecessors:
                if isinstance(pred, LiteralDataNode):
                    # Determine which side this predecessor feeds
                    if f"df_{pred.node_id}" in right_var or right_var in (f"df_{pred.node_id}",):
                        broadcast_side = "right"
                    elif f"df_{pred.node_id}" in left_var or left_var in (f"df_{pred.node_id}",):
                        broadcast_side = "left"
                    break

        # Apply broadcast wrapping
        join_left = left_var
        join_right = right_var
        if broadcast_side == "right":
            join_right = f"F.broadcast({right_var})"
        elif broadcast_side == "left":
            join_left = f"F.broadcast({left_var})"

        if need_join or (not need_left and not need_right):
            # Build post-join column ops as a single chain: batched renames first,
            # then drops. Use .withColumnsRenamed({...}) (Spark 3.4+, DBR 14.3 LTS+)
            # to avoid the quadratic schema-rebuild cost of a long
            # .withColumnRenamed chain.
            post_ops: list[str] = []
            renames: list[tuple[str, str]] = []
            for op in node.select_left + node.select_right:
                if op.action.value == "rename" and op.rename_to and op.rename_to != op.field_name:
                    renames.append((op.field_name, op.rename_to))
            if renames:
                rename_entries = ", ".join(f'"{old}": "{new}"' for old, new in renames)
                post_ops.append(f"    .withColumnsRenamed({{{rename_entries}}})")
            drops_post = []
            for op in node.select_left + node.select_right:
                if not op.selected:
                    drop_name = op.rename_to if (op.rename_to and op.rename_to != op.field_name) else op.field_name
                    drops_post.append(f'"{drop_name}"')
            if drops_post:
                post_ops.append(f"    .drop({', '.join(drops_post)})")

            if post_ops:
                chain_body = "\n".join(post_ops)
                lines.append(
                    f'{out_join} = (\n    {join_left}.join({join_right}, {condition}, "{join_type}")\n{chain_body}\n)'
                )
            else:
                lines.append(f'{out_join} = {join_left}.join({join_right}, {condition}, "{join_type}")')
            output_vars["Join"] = out_join
            output_vars["Output"] = out_join
        if need_left:
            lines.append(f'{out_left} = {left_var}.join({right_var}, {condition}, "left_anti")')
            output_vars["Left"] = out_left
        if need_right:
            lines.append(f'{out_right} = {right_var}.join({left_var}, {condition}, "left_anti")')
            output_vars["Right"] = out_right

        if "Output" not in output_vars:
            output_vars["Output"] = out_join

        return NodeCodeResult(
            code_lines=lines,
            output_vars=output_vars,
            warnings=warnings,
        )

    def _generate_UnionNode(self, node: UnionNode, input_vars: dict[str, str]) -> NodeCodeResult:
        out_var = f"df_{node.node_id}"
        sorted_vars = list(input_vars.values())

        if len(sorted_vars) == 0:
            lines = [f"{out_var} = spark.createDataFrame([], schema=[])  # empty union"]
        elif len(sorted_vars) == 1:
            lines = [f"{out_var} = {sorted_vars[0]}"]
        else:
            allow_missing = "True" if node.allow_missing else "False"
            parts = [sorted_vars[0]]
            for sv in sorted_vars[1:]:
                parts.append(f".unionByName({sv}, allowMissingColumns={allow_missing})")
            lines = [f"{out_var} = " + "".join(parts)]

        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
        )

    def _generate_AppendFieldsNode(self, node: AppendFieldsNode, input_vars: dict[str, str]) -> NodeCodeResult:
        target = input_vars.get("Targets", input_vars.get("Target", input_vars.get("Input", "MISSING_TARGET")))
        source = input_vars.get("Source", "MISSING_SOURCE")
        out_var = f"df_{node.node_id}"

        warnings: list[str] = []
        lines = [
            "# AppendFields: cross join with broadcast (source should be a single-row lookup)",
            f"{out_var} = {target}.crossJoin(F.broadcast({source}.limit(1)))",
        ]
        warnings.append(
            f"AppendFields node {node.node_id}: source limited to 1 row via .limit(1). "
            "Remove .limit(1) if source intentionally has multiple rows."
        )
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=warnings,
        )

    def _generate_FindReplaceNode(self, node: FindReplaceNode, input_vars: dict[str, str]) -> NodeCodeResult:
        target_var = input_vars.get("Input", input_vars.get("Target", "MISSING_TARGET"))
        lookup_var = input_vars.get("Source", input_vars.get("Right", target_var))
        out_var = f"df_{node.node_id}"
        warnings: list[str] = []

        find_field = node.find_field or "find_field"
        replace_field = node.replace_field or "replace_field"

        lines = [f"# FindReplace: find '{find_field}', replace with '{replace_field}' (mode: {node.find_mode})"]

        if node.find_mode == "exact":
            if not node.case_sensitive:
                lines.append(
                    f'_lookup_{node.node_id} = {lookup_var}.withColumn("_find_key", F.lower(F.col("{find_field}")))'
                )
                lines.append(
                    f'_main_{node.node_id} = {target_var}.withColumn("_find_key", F.lower(F.col("{find_field}")))'
                )
                join_cond = f'_main_{node.node_id}["_find_key"] == _lookup_{node.node_id}["_find_key"]'
                lines.append(
                    f'{out_var} = _main_{node.node_id}.join(_lookup_{node.node_id}.select("_find_key", F.col("{replace_field}").alias("_replace_val_{node.node_id}")), {join_cond}, "left")'
                )
                lines.append(
                    f'{out_var} = {out_var}.withColumn("{find_field}", F.coalesce(F.col("_replace_val_{node.node_id}"), F.col("{find_field}")))'
                )
                lines.append(f'{out_var} = {out_var}.drop("_find_key", "_replace_val_{node.node_id}")')
            else:
                lines.append(
                    f'_lookup_{node.node_id} = {lookup_var}.select(F.col("{find_field}").alias("_find_val"), F.col("{replace_field}").alias("_replace_val_{node.node_id}"))'
                )
                lines.append(
                    f'{out_var} = {target_var}.join(_lookup_{node.node_id}, {target_var}["{find_field}"] == _lookup_{node.node_id}["_find_val"], "left")'
                )
                lines.append(
                    f'{out_var} = {out_var}.withColumn("{find_field}", F.coalesce(F.col("_replace_val_{node.node_id}"), F.col("{find_field}")))'
                )
                lines.append(f'{out_var} = {out_var}.drop("_find_val", "_replace_val_{node.node_id}")')
        elif node.find_mode == "contains":
            # Collect lookup values (small table) and apply regexp_replace for each
            lines.append("# Contains-mode find/replace: collect lookup pairs, apply sequentially")
            lines.append(f'_pairs_{node.node_id} = {lookup_var}.select("{find_field}", "{replace_field}").collect()')
            lines.append(f"{out_var} = {target_var}")
            # `target_fields` is not a field on FindReplaceNode (yet) — guard
            # with getattr so older IR objects fall back to the find_field.
            _tf = getattr(node, "target_fields", None)
            target_col = _tf[0] if _tf else find_field
            lines.append(f"for _pair in _pairs_{node.node_id}:")
            lines.append(
                f'    {out_var} = {out_var}.withColumn("{target_col}", F.regexp_replace(F.col("{target_col}"), F.lit(_pair["{find_field}"]), F.lit(_pair["{replace_field}"])))'
            )
            warnings.append(
                f"FindReplace contains mode (node {node.node_id}): lookup table collected to driver — ensure it is small"
            )
        elif node.find_mode == "regex":
            # Same approach but patterns are regex
            lines.append("# Regex-mode find/replace: collect lookup patterns, apply sequentially")
            lines.append(f'_pairs_{node.node_id} = {lookup_var}.select("{find_field}", "{replace_field}").collect()')
            lines.append(f"{out_var} = {target_var}")
            # `target_fields` is not a field on FindReplaceNode (yet) — guard
            # with getattr so older IR objects fall back to the find_field.
            _tf = getattr(node, "target_fields", None)
            target_col = _tf[0] if _tf else find_field
            lines.append(f"for _pair in _pairs_{node.node_id}:")
            lines.append(
                f'    {out_var} = {out_var}.withColumn("{target_col}", F.regexp_replace(F.col("{target_col}"), _pair["{find_field}"], _pair["{replace_field}"]))'
            )
            warnings.append(
                f"FindReplace regex mode (node {node.node_id}): lookup table collected to driver — ensure it is small"
            )
        else:
            lines.append(f"{out_var} = {target_var}")
            warnings.append(f"FindReplace mode '{node.find_mode}' (node {node.node_id}) may need manual adjustment")

        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=warnings,
        )

    def _generate_JoinMultipleNode(self, node: JoinMultipleNode, input_vars: dict[str, str]) -> NodeCodeResult:
        out_var = f"df_{node.node_id}"
        sorted_inputs = list(input_vars.items())

        if len(sorted_inputs) < 2:
            var = sorted_inputs[0][1] if sorted_inputs else "MISSING_INPUT"
            lines = [f"{out_var} = {var}"]
        else:
            join_type = node.join_type or "inner"
            lines = [f"{out_var} = {sorted_inputs[0][1]}"]

            for i, (_anchor, var_name) in enumerate(sorted_inputs[1:], start=1):
                if node.join_keys:
                    # Use key fields - handle potential column name conflicts with aliases
                    key_parts = [
                        f'{out_var}["{jk.left_field}"] == {var_name}["{jk.right_field}"]' for jk in node.join_keys
                    ]
                    condition = " & ".join(f"({kp})" for kp in key_parts)
                    if len(key_parts) == 1:
                        condition = key_parts[0]
                    lines.append(f'{out_var} = {out_var}.join({var_name}, {condition}, "{join_type}")')
                else:
                    # No explicit keys - join on common column names
                    lines.append(f"# Join input #{i + 1} (no explicit keys - joining on common columns)")
                    lines.append(f'{out_var} = {out_var}.join({var_name}, "{join_type}")')

        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
        )

    # -- Parse nodes --------------------------------------------------------

    def _generate_RegExNode(self, node: RegExNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"

        if node.mode == "replace":
            lines = [
                f'{out_var} = {inp}.withColumn("{node.field_name}", '
                f'F.regexp_replace(F.col("{node.field_name}"), "{node.expression}", "{node.replacement}"))'
            ]
        elif node.mode == "parse":
            lines = [f"{out_var} = {inp}"]
            for idx, out_field in enumerate(node.output_fields):
                lines.append(
                    f'{out_var} = {out_var}.withColumn("{out_field}", '
                    f'F.regexp_extract(F.col("{node.field_name}"), "{node.expression}", {idx + 1}))'
                )
        elif node.mode == "match":
            lines = [
                f'{out_var} = {inp}.withColumn("_regex_match_{node.node_id}", '
                f'F.col("{node.field_name}").rlike("{node.expression}"))',
            ]
        else:
            lines = [
                f"# RegEx mode '{node.mode}' for field '{node.field_name}'",
                "# TODO: Manual conversion required.",
                f"{out_var} = {inp}",
            ]

        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
        )

    def _generate_TextToColumnsNode(self, node: TextToColumnsNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        root = node.output_root_name or node.field_name

        if node.split_to == "rows":
            lines = [
                f'{out_var} = {inp}.withColumn("{root}", F.explode(F.split(F.col("{node.field_name}"), "{node.delimiter}")))',
            ]
        else:
            num = node.num_columns or 5
            entries = ",\n    ".join(f'"{root}_{i + 1}": _split_{node.node_id}[{i}]' for i in range(num))
            lines = [
                f'_split_{node.node_id} = F.split(F.col("{node.field_name}"), "{node.delimiter}")',
                f"{out_var} = {inp}.withColumns({{\n    {entries},\n}})",
            ]

        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
        )

    def _generate_DateTimeNode(self, node: DateTimeNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        out_field = node.output_field or f"{node.input_field}_converted"

        if node.conversion_mode == "parse":
            fmt = alteryx_fmt_to_spark(node.format_string or "yyyy-MM-dd")
            lines = [f'{out_var} = {inp}.withColumn("{out_field}", F.to_date(F.col("{node.input_field}"), "{fmt}"))']
        elif node.conversion_mode == "format":
            fmt = alteryx_fmt_to_spark(node.format_string or "yyyy-MM-dd")
            lines = [
                f'{out_var} = {inp}.withColumn("{out_field}", F.date_format(F.col("{node.input_field}"), "{fmt}"))'
            ]
        elif node.conversion_mode == "now":
            lines = [f'{out_var} = {inp}.withColumn("{out_field}", F.current_timestamp())']
        else:
            lines = [
                f"# DateTime conversion mode: {node.conversion_mode}",
                f'{out_var} = {inp}.withColumn("{out_field}", F.col("{node.input_field}"))',
            ]

        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
        )

    def _generate_JsonParseNode(self, node: JsonParseNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        out_field = node.output_field or f"{node.input_field}_parsed"

        lines = [
            f"# JSON parse from field '{node.input_field}' (flatten: {node.flatten_mode})",
            f'{out_var} = {inp}.withColumn("{out_field}", F.get_json_object(F.col("{node.input_field}"), "$"))',
        ]
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
        )

    # -- Transform nodes ----------------------------------------------------

    def _generate_SummarizeNode(self, node: SummarizeNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"

        group_by_fields: list[str] = []
        agg_exprs: list[str] = []

        agg_map = {
            AggAction.SUM: "F.sum",
            AggAction.COUNT: "F.count",
            AggAction.COUNT_DISTINCT: "F.countDistinct",
            AggAction.MIN: "F.min",
            AggAction.MAX: "F.max",
            AggAction.AVG: "F.avg",
            AggAction.FIRST: "F.first",
            AggAction.LAST: "F.last",
            AggAction.STD_DEV: "F.stddev",
            AggAction.VARIANCE: "F.variance",
        }

        for agg in node.aggregations:
            if agg.action == AggAction.GROUP_BY:
                group_by_fields.append(f'"{agg.field_name}"')
            elif agg.action in agg_map:
                func = agg_map[agg.action]
                alias = agg.output_field_name or f"{agg.action.value}_{agg.field_name}"
                agg_exprs.append(f'{func}("{agg.field_name}").alias("{alias}")')
            elif agg.action == AggAction.CONCAT:
                alias = agg.output_field_name or f"Concat_{agg.field_name}"
                sep = agg.separator or ","
                agg_exprs.append(f'F.concat_ws("{sep}", F.collect_list("{agg.field_name}")).alias("{alias}")')
            elif agg.action == AggAction.COUNT_NON_NULL:
                alias = agg.output_field_name or f"CountNonNull_{agg.field_name}"
                agg_exprs.append(f'F.count(F.when(F.col("{agg.field_name}").isNotNull(), 1)).alias("{alias}")')
            elif agg.action == AggAction.COUNT_NULL:
                alias = agg.output_field_name or f"CountNull_{agg.field_name}"
                agg_exprs.append(f'F.count(F.when(F.col("{agg.field_name}").isNull(), 1)).alias("{alias}")')
            else:
                alias = agg.output_field_name or f"{agg.action.value}_{agg.field_name}"
                agg_exprs.append(f'F.expr("{agg.action.value.lower()}(`{agg.field_name}`)").alias("{alias}")')

        gb = ", ".join(group_by_fields)
        aggs = ", ".join(agg_exprs) if agg_exprs else 'F.count("*").alias("count")'

        if group_by_fields:
            lines = [f"{out_var} = {inp}.groupBy({gb}).agg({aggs})"]
        else:
            lines = [f"{out_var} = {inp}.agg({aggs})"]

        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
        )

    def _generate_CrossTabNode(self, node: CrossTabNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"

        group_cols = ", ".join(f'"{gf}"' for gf in node.group_fields) if node.group_fields else ""
        agg_func = node.aggregation.lower() if node.aggregation else "sum"

        lines = [
            f'{out_var} = {inp}.groupBy({group_cols}).pivot("{node.header_field}").agg(F.{agg_func}("{node.value_field}"))',
        ]
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
        )

    def _generate_TransposeNode(self, node: TransposeNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"

        key_cols = ", ".join(f'"`{kf}`"' for kf in node.key_fields) if node.key_fields else ""
        data_fields = node.data_fields if node.data_fields else []

        if data_fields:
            cols_str = ", ".join(f"'{df}', `{df}`" for df in data_fields)
            lines = [
                "# Transpose (unpivot): data fields -> rows",
                f"{out_var} = {inp}.selectExpr({key_cols + ', ' if key_cols else ''}"
                f'"stack({len(data_fields)}, {cols_str}) as (`{node.header_name}`, `{node.value_name}`)")',
            ]
        else:
            lines = [
                "# Transpose: TODO - determine data columns at runtime",
                f"{out_var} = {inp}  # placeholder for transpose",
            ]

        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
        )

    def _generate_RunningTotalNode(self, node: RunningTotalNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"

        if node.group_fields:
            partition = ", ".join(f'"{gf}"' for gf in node.group_fields)
            window_def = (
                f"Window.partitionBy({partition})"
                f".orderBy(F.monotonically_increasing_id())"
                f".rowsBetween(Window.unboundedPreceding, Window.currentRow)"
            )
        else:
            window_def = (
                "Window.orderBy(F.monotonically_increasing_id())"
                ".rowsBetween(Window.unboundedPreceding, Window.currentRow)"
            )

        lines = [f"_window_{node.node_id} = {window_def}", f"{out_var} = {inp}"]

        func_map = {"Sum": "F.sum", "Avg": "F.avg", "Count": "F.count", "Min": "F.min", "Max": "F.max"}

        for rf in node.running_fields:
            func = func_map.get(rf.running_type, "F.sum")
            alias = rf.output_field_name or f"Running{rf.running_type}_{rf.field_name}"
            lines.append(
                f'{out_var} = {out_var}.withColumn("{alias}", {func}("{rf.field_name}").over(_window_{node.node_id}))'
            )

        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
        )

    def _generate_CountRecordsNode(self, node: CountRecordsNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        lines = [f'{out_var} = spark.createDataFrame([({inp}.count(),)], ["{node.output_field}"])']
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
        )

    # -- Developer nodes ----------------------------------------------------

    def _generate_PythonToolNode(self, node: PythonToolNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"

        code_lines_raw = node.code.split("\n") if node.code else ["# (no code)"]
        commented = [f"#   {line}" for line in code_lines_raw]

        lines = [
            f"# ---- PythonTool (node {node.node_id}) ----",
            "# MANUAL REVIEW REQUIRED: Original Alteryx Python code below",
            *commented,
            "# ---- End PythonTool ----",
            f"{out_var} = {inp}  # passthrough placeholder",
        ]
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=[f"PythonTool (node {node.node_id}) requires manual review"],
        )

    def _generate_DownloadNode(self, node: DownloadNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        url = node.url_static or f"<from field: {node.url_field}>"
        lines = [
            f"# DownloadTool: {node.method} {url}",
            "# TODO: Replace with requests/urllib UDF or Databricks external access.",
            f"{out_var} = {inp}  # passthrough placeholder",
        ]
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=[f"DownloadTool (node {node.node_id}) requires manual conversion"],
        )

    def _generate_RunCommandNode(self, node: RunCommandNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        lines = [
            f"# RunCommand: '{node.command} {node.command_arguments}'",
            "# TODO: Replace with subprocess or %sh magic in Databricks.",
            f"{out_var} = {inp}  # passthrough placeholder",
        ]
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=[f"RunCommand (node {node.node_id}) requires manual conversion"],
        )

    # -- New tool nodes -----------------------------------------------------

    def _generate_ImputationNode(self, node: ImputationNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        lines = [f"# Imputation: fill missing values (method: {node.method})"]
        lines.append(f"{out_var} = {inp}")
        if node.method == "custom" and node.custom_value is not None:
            fill_dict = ", ".join(f'"{f}": "{node.custom_value}"' for f in node.fields)
            lines.append(f"{out_var} = {out_var}.na.fill({{{fill_dict}}})")
        elif node.method in ("mean", "avg"):
            for fld in node.fields:
                lines.append(f'_mean_{fld}_{node.node_id} = {out_var}.agg(F.avg("{fld}")).first()[0]')
                lines.append(f'{out_var} = {out_var}.na.fill({{"{fld}": _mean_{fld}_{node.node_id}}})')
        elif node.method == "median":
            for fld in node.fields:
                lines.append(f'_median_{fld}_{node.node_id} = {out_var}.approxQuantile("{fld}", [0.5], 0.001)[0]')
                lines.append(f'{out_var} = {out_var}.na.fill({{"{fld}": _median_{fld}_{node.node_id}}})')
        elif node.method == "mode":
            for fld in node.fields:
                lines.append(
                    f'_mode_{fld}_{node.node_id} = {out_var}.groupBy("{fld}").count().orderBy(F.desc("count")).first()[0]'
                )
                lines.append(f'{out_var} = {out_var}.na.fill({{"{fld}": _mode_{fld}_{node.node_id}}})')
        else:
            lines.append(f'{out_var} = {out_var}.na.fill("")')
        return NodeCodeResult(code_lines=lines, output_vars={"Output": out_var})

    def _generate_XMLParseNode(self, node: XMLParseNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        lines = [f"# XMLParse: extract XPath values from '{node.input_field}'"]
        lines.append(f"{out_var} = {inp}")
        if node.xpath_expressions:
            for xpath, name in node.xpath_expressions:
                lines.append(
                    f'{out_var} = {out_var}.withColumn("{name}", F.xpath_string(F.col("{node.input_field}"), F.lit("{xpath}")))'
                )
        elif node.output_field:
            lines.append(f'{out_var} = {out_var}.withColumn("{node.output_field}", F.col("{node.input_field}"))')
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=[f"XMLParse (node {node.node_id}): verify xpath_string function availability"]
            if node.xpath_expressions
            else [],
        )

    def _generate_TileNode(self, node: TileNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        imports = {"from pyspark.sql import Window"}
        order = (
            f'"{node.order_field}"'
            if node.order_field
            else f'"{node.tile_field}"'
            if node.tile_field
            else "F.monotonically_increasing_id()"
        )
        if node.group_fields:
            partition = ", ".join(f'"{gf}"' for gf in node.group_fields)
            window = f"Window.partitionBy({partition}).orderBy({order})"
        else:
            window = f"Window.orderBy({order})"
        lines = [
            f"# Tile: assign rows to {node.tile_count} equal-sized groups",
            f'{out_var} = {inp}.withColumn("{node.output_field}", F.ntile({node.tile_count}).over({window}))',
        ]
        return NodeCodeResult(code_lines=lines, output_vars={"Output": out_var}, imports=imports)

    def _generate_WeightedAverageNode(self, node: WeightedAverageNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        lines = [f"# WeightedAverage: sum({node.value_field} * {node.weight_field}) / sum({node.weight_field})"]
        if node.group_fields:
            gb = ", ".join(f'"{gf}"' for gf in node.group_fields)
            lines.append(
                f"{out_var} = {inp}.groupBy({gb}).agg("
                f'(F.sum(F.col("{node.value_field}") * F.col("{node.weight_field}")) / F.sum(F.col("{node.weight_field}"))).alias("{node.output_field}")'
                f")"
            )
        else:
            lines.append(
                f"{out_var} = {inp}.agg("
                f'(F.sum(F.col("{node.value_field}") * F.col("{node.weight_field}")) / F.sum(F.col("{node.weight_field}"))).alias("{node.output_field}")'
                f")"
            )
        return NodeCodeResult(code_lines=lines, output_vars={"Output": out_var})

    def _generate_DynamicInputNode(self, node: DynamicInputNode, input_vars: dict[str, str]) -> NodeCodeResult:
        out_var = f"df_{node.node_id}"
        inp = self._get_single_input(input_vars) if input_vars else None

        if node.mode == "ModifySQL" and node.template_query and inp:
            # Emit a loop: for each row from the input df, substitute placeholders
            # in the SQL template and execute via spark.sql(), then union results.
            normalized_template, _sql_warns = normalize_sql_for_spark(node.template_query)
            escaped_sql = normalized_template.replace('"""', '\\"\\"\\"')
            # Detect which modifications use ISO date placeholders
            iso_date_mods = {
                mod["field"]
                for mod in node.modifications
                if _ISO_DATE_PLACEHOLDER_RE.match(mod["replace_text"].strip())
            }

            lines: list[str] = [
                f"# DynamicInput (ModifySQL): executes parameterized SQL once per row of {inp}",
                f"# Source connection: {node.template_connection}",
                # Driver-collect safety guard (session): fail fast if the
                # input is too large to fit on the driver, before we collect.
                f"# WARNING: This collects the input DataFrame to the driver. Ensure {inp} is small (<10k rows).",
                f"_n_{node.node_id} = {inp}.count()",
                f"assert _n_{node.node_id} <= 10000, f'DynamicInput node {node.node_id}: input has {{_n_{node.node_id}}} rows — too large for driver collect. Filter or sample first.'",
                # UC migration hints (main): show the three common patterns
                # so customers can pick the right replacement for their setup.
                "# TODO: Replace the connection below with your Unity Catalog equivalent. Options:",
                '#   spark.table("catalog.schema.table_name")                       # UC managed/external table',
                '#   spark.sql("SELECT ... FROM catalog.schema.table_name")         # keep SQL, update table ref',
                '#   spark.read.format("jdbc").option("url","jdbc:...").option("dbtable","schema.table").load()  # JDBC',
            ]

            # Emit ISO date normalization helper if any placeholder is an ISO date
            if iso_date_mods:
                nid = node.node_id
                lines += [
                    f"def _to_iso_date_{nid}(val):",
                    '    """Normalize val to ISO date string yyyy-MM-dd for SQL replacement."""',
                    "    if val is None: return 'NULL'",
                    "    s = str(val)",
                    "    if len(s) == 10 and s[4:5] == '-' and s[7:8] == '-': return s  # already ISO",
                    "    from datetime import datetime",
                    "    for _fmt in ('%d-%b-%Y', '%b-%d-%Y', '%m/%d/%Y', '%d/%m/%Y', '%Y%m%d'):",
                    "        try:",
                    "            return datetime.strptime(s, _fmt).strftime('%Y-%m-%d')",
                    "        except ValueError:",
                    "            pass",
                    "    return s",
                ]

            lines += [
                f"_rows_{node.node_id} = {inp}.collect()",
                f"_dfs_{node.node_id} = []",
                f"for _row in _rows_{node.node_id}:",
                f'    _sql_{node.node_id} = """{escaped_sql}"""',
            ]
            for mod in node.modifications:
                f_name = mod["field"]
                placeholder = mod["replace_text"]
                if _ISO_DATE_PLACEHOLDER_RE.match(placeholder.strip()):
                    lines.append(
                        f'    _sql_{node.node_id} = _sql_{node.node_id}.replace("{placeholder}", _to_iso_date_{node.node_id}(_row["{f_name}"]))'
                    )
                else:
                    lines.append(
                        f'    _sql_{node.node_id} = _sql_{node.node_id}.replace("{placeholder}", str(_row["{f_name}"]))'
                    )
            lines += [
                f"    _dfs_{node.node_id}.append(spark.sql(_sql_{node.node_id}))",
                "from pyspark.sql.types import StructType",
                f"{out_var} = _dfs_{node.node_id}[0] if _dfs_{node.node_id} else spark.createDataFrame([], StructType([]))",
                f"for _df in _dfs_{node.node_id}[1:]:",
                f"    {out_var} = {out_var}.unionByName(_df, allowMissingColumns=True)",
            ]
            return NodeCodeResult(
                code_lines=lines,
                output_vars={"Output": out_var},
                warnings=[f"DynamicInput node {node.node_id}: SQL loop generated — map connection to Databricks"],
            )

        # Fallback: file-pattern mode or unrecognised mode
        fmt = self._map_file_format(node.file_format)
        pattern = node.file_path_pattern or "*.csv"
        lines = [
            "# DynamicInput: read multiple files matching pattern",
            "# TODO: Adjust path pattern for Databricks DBFS / Unity Catalog Volume",
            f'{out_var} = spark.read.format("{fmt}").option("header", "true").load("{self._esc(pattern)}")',
        ]
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=[f"DynamicInput (node {node.node_id}): adjust file path pattern for Databricks"],
        )

    def _generate_DynamicOutputNode(self, node: DynamicOutputNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        fmt = self._map_file_format(node.file_format)
        path = node.file_path_expression or "dynamic_output"
        lines = ["# DynamicOutput: write to partitioned destination"]
        if node.partition_field:
            lines.append(
                f'{inp}.write.format("{fmt}").partitionBy("{node.partition_field}").mode("overwrite").save("{path}")'
            )
        else:
            lines.append(f'{inp}.write.format("{fmt}").mode("overwrite").save("{path}")')
        lines.append(f"{out_var} = {inp}  # passthrough after write")
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=[f"DynamicOutput (node {node.node_id}): adjust output path for Databricks"],
        )

    # -- Workflow / Interface / Reporting nodes ------------------------------

    def _generate_WorkflowControlNode(self, node: WorkflowControlNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars) if input_vars else None
        lines = [f"# {node.original_tool_type}: {node.control_type} - no Databricks equivalent"]
        # Pass inp through directly — no identity assignment
        return NodeCodeResult(code_lines=lines, output_vars={"Output": inp} if inp else {})

    def _generate_MacroIONode(self, node: MacroIONode, input_vars: dict[str, str]) -> NodeCodeResult:
        out_var = f"df_{node.node_id}"
        if node.direction == "input":
            esc_fn = self._esc(node.field_name)
            default = f', "{self._esc(node.default_value)}"' if node.default_value else ""
            lines = [
                f"# MacroInput: {node.field_name}",
                f'dbutils.widgets.text("{esc_fn}"{default})',
                f'{out_var}_param = dbutils.widgets.get("{esc_fn}")',
            ]
        else:
            inp = self._get_single_input(input_vars) if input_vars else None
            lines = [f"# MacroOutput: {node.field_name}"]
            if inp:
                lines.append(f"{out_var} = {inp}")
        return NodeCodeResult(
            code_lines=lines, output_vars={"Output": out_var} if node.direction == "output" and input_vars else {}
        )

    def _generate_FieldSummaryNode(self, node: FieldSummaryNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        if node.fields:
            cols = ", ".join(f'"{f}"' for f in node.fields)
            lines = [f"{out_var} = {inp}.select({cols}).describe()"]
        else:
            lines = [f"{out_var} = {inp}.describe()"]
        return NodeCodeResult(code_lines=lines, output_vars={"Output": out_var})

    def _generate_WidgetNode(self, node: WidgetNode, input_vars: dict[str, str]) -> NodeCodeResult:
        esc_name = self._esc(node.field_name)
        default = f', "{self._esc(node.default_value)}"' if node.default_value else ""
        if node.widget_type in ("dropdown", "listbox") and node.options:
            choices = ", ".join(f'"{self._esc(o)}"' for o in node.options)
            lines = [
                f'dbutils.widgets.dropdown("{esc_name}", "{self._esc(node.options[0]) if node.options else ""}",  [{choices}])'
            ]
        elif node.widget_type == "checkbox":
            lines = [f'dbutils.widgets.dropdown("{esc_name}", "False", ["True", "False"])']
        else:
            lines = [f'dbutils.widgets.text("{esc_name}"{default})']
        lines.append(f'# Widget: {node.widget_type} - "{node.label or node.field_name}"')
        return NodeCodeResult(code_lines=lines, output_vars={})

    def _generate_CloudStorageNode(self, node: CloudStorageNode, input_vars: dict[str, str]) -> NodeCodeResult:
        out_var = f"df_{node.node_id}"
        fmt = self._map_file_format(node.file_format)
        if node.provider == "s3":
            path_prefix = "s3://"
        elif node.provider == "azure":
            path_prefix = "abfss://"
        else:
            path_prefix = ""
        full_path = f"{path_prefix}{node.bucket_or_container}/{node.path}" if node.bucket_or_container else node.path
        if node.direction == "input":
            lines = [f'{out_var} = spark.read.format("{fmt}").option("header", "true").load("{self._esc(full_path)}")']
            return NodeCodeResult(code_lines=lines, output_vars={"Output": out_var})
        else:
            inp = self._get_single_input(input_vars)
            lines = [f'{inp}.write.format("{fmt}").mode("overwrite").save("{full_path}")', f"{out_var} = {inp}"]
            return NodeCodeResult(code_lines=lines, output_vars={"Output": out_var})

    def _generate_ChartNode(self, node: ChartNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        title = node.title or "Chart"
        lines = [
            f"# Chart: {node.chart_type or 'auto'} - {title}",
            f"# Use display({inp}) or convert to pandas for matplotlib/plotly",
            f"display({inp})",
            f"{out_var} = {inp}",
        ]
        return NodeCodeResult(code_lines=lines, output_vars={"Output": out_var})

    def _generate_ReportNode(self, node: ReportNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        lines = [
            f"# Report ({node.report_type}): {node.title or 'Untitled'}",
            f"display({inp})",
            f"{out_var} = {inp}",
        ]
        return NodeCodeResult(code_lines=lines, output_vars={"Output": out_var})

    def _generate_EmailOutputNode(self, node: EmailOutputNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        lines = [
            "# EmailOutput: use Databricks notifications or smtplib",
            f"# To: {node.to_field}, Subject: {node.subject_field}",
            "# Consider using dbutils.notebook.exit() with results or Databricks alerts",
            f"{out_var} = {inp}",
        ]
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=[f"EmailOutput (node {node.node_id}): manual conversion needed for email sending"],
        )

    # -- Spatial nodes ------------------------------------------------------

    def _generate_BufferNode(self, node: BufferNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        lines = [
            "# Buffer: create buffer zone using Databricks Mosaic library",
            "# Requires: import mosaic; mosaic.enable_mosaic(spark)",
            f'{out_var} = {inp}.withColumn("{node.input_field}_buffer", '
            f'F.expr("st_buffer({node.input_field}, {node.buffer_distance})"))',
        ]
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=[f"BufferNode (node {node.node_id}): requires Databricks Mosaic library (st_buffer)"],
        )

    def _generate_SpatialMatchNode(self, node: SpatialMatchNode, input_vars: dict[str, str]) -> NodeCodeResult:
        left_var = input_vars.get("Target", input_vars.get("Left", input_vars.get("Input", "MISSING_TARGET")))
        right_var = input_vars.get("Universe", input_vars.get("Right", "MISSING_UNIVERSE"))
        out_var = f"df_{node.node_id}"
        lines = [
            "# Spatial match using Mosaic st_intersects",
            "# Requires: import mosaic; mosaic.enable_mosaic(spark)",
            f"{out_var} = {left_var}.join({right_var}, "
            f'F.expr("st_intersects({left_var}.{node.spatial_field_target}, '
            f'{right_var}.{node.spatial_field_universe})"), "inner")',
        ]
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=[f"SpatialMatchNode (node {node.node_id}): requires Databricks Mosaic library (st_intersects)"],
        )

    def _generate_CreatePointsNode(self, node: CreatePointsNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        lines = [
            "# CreatePoints: build point geometry from lat/lon",
            f'{out_var} = {inp}.withColumn("{node.output_field}", '
            f'F.struct(F.col("{node.lat_field}"), F.col("{node.lon_field}")))',
        ]
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
        )

    def _generate_DistanceNode(self, node: DistanceNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        # Earth radius: 3959 miles, 6371 km
        radius = "3959" if node.distance_units == "miles" else "6371"
        lines = [
            f"# Distance: Haversine formula ({node.distance_units})",
            f"# Using source='{node.source_field}' and target='{node.target_field}'",
            f'_lat1_{node.node_id} = F.radians(F.col("{node.source_field}.lat"))',
            f'_lon1_{node.node_id} = F.radians(F.col("{node.source_field}.lon"))',
            f'_lat2_{node.node_id} = F.radians(F.col("{node.target_field}.lat"))',
            f'_lon2_{node.node_id} = F.radians(F.col("{node.target_field}.lon"))',
            f"_distance_expr_{node.node_id} = F.acos(",
            f"    F.sin(_lat1_{node.node_id}) * F.sin(_lat2_{node.node_id}) +",
            f"    F.cos(_lat1_{node.node_id}) * F.cos(_lat2_{node.node_id}) *",
            f"    F.cos(_lon2_{node.node_id} - _lon1_{node.node_id})",
            f") * {radius}",
            f'{out_var} = {inp}.withColumn("{node.output_field}", _distance_expr_{node.node_id})',
        ]
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=[f"DistanceNode (node {node.node_id}): verify lat/lon struct field names match your schema"],
        )

    def _generate_FindNearestNode(self, node: FindNearestNode, input_vars: dict[str, str]) -> NodeCodeResult:
        target_var = input_vars.get("Target", input_vars.get("Left", input_vars.get("Input", "MISSING_TARGET")))
        universe_var = input_vars.get("Universe", input_vars.get("Right", "MISSING_UNIVERSE"))
        out_var = f"df_{node.node_id}"
        radius = "3959" if node.distance_units == "miles" else "6371"
        lines = [
            f"# FindNearest: cross join + Haversine distance + rank (max_matches={node.max_matches})",
            f"_cross_{node.node_id} = {target_var}.crossJoin({universe_var})",
            "# Compute Haversine distance between target and universe points",
            f'_lat1_{node.node_id} = F.radians(F.col("{node.target_field}.lat"))',
            f'_lon1_{node.node_id} = F.radians(F.col("{node.target_field}.lon"))',
            f'_lat2_{node.node_id} = F.radians(F.col("{node.universe_field}.lat"))',
            f'_lon2_{node.node_id} = F.radians(F.col("{node.universe_field}.lon"))',
            f"_dist_expr_{node.node_id} = F.acos(",
            f"    F.sin(_lat1_{node.node_id}) * F.sin(_lat2_{node.node_id}) +",
            f"    F.cos(_lat1_{node.node_id}) * F.cos(_lat2_{node.node_id}) *",
            f"    F.cos(_lon2_{node.node_id} - _lon1_{node.node_id})",
            f") * {radius}",
            f'_with_dist_{node.node_id} = _cross_{node.node_id}.withColumn("{node.output_distance_field}", _dist_expr_{node.node_id})',
            f'_window_{node.node_id} = Window.partitionBy({target_var}.columns[0]).orderBy(F.col("{node.output_distance_field}"))',
            f'_ranked_{node.node_id} = _with_dist_{node.node_id}.withColumn("_rank_{node.node_id}", F.row_number().over(_window_{node.node_id}))',
            f'{out_var} = _ranked_{node.node_id}.filter(F.col("_rank_{node.node_id}") <= {node.max_matches}).drop("_rank_{node.node_id}")',
        ]
        warnings = [f"FindNearestNode (node {node.node_id}): verify partition key and lat/lon struct field names"]
        if node.max_distance is not None:
            lines.insert(
                -1,
                f'{out_var} = _with_dist_{node.node_id}.filter(F.col("{node.output_distance_field}") <= {node.max_distance})',
            )
            warnings.append(
                f"FindNearestNode (node {node.node_id}): max_distance={node.max_distance} {node.distance_units} filter applied"
            )
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=warnings,
        )

    def _generate_GeocoderNode(self, node: GeocoderNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        address_fields = [
            f for f in [node.address_field, node.city_field, node.state_field, node.zip_field, node.country_field] if f
        ]
        lines = [
            "# Geocoder: convert address fields to coordinates",
            f"# Input fields: {', '.join(address_fields)}",
            "# TODO: Implement geocoding UDF using a geocoding service (e.g., Databricks Labs Mosaic, Google Maps API, HERE, etc.)",
            "# Example: register a pandas UDF that calls a geocoding API",
            f"{out_var} = {inp}  # passthrough placeholder",
            f'# {out_var} = {out_var}.withColumn("{node.output_lat_field}", <geocode_lat_udf>)',
            f'# {out_var} = {out_var}.withColumn("{node.output_lon_field}", <geocode_lon_udf>)',
        ]
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=[f"GeocoderNode (node {node.node_id}): requires manual implementation of geocoding UDF"],
        )

    def _generate_TradeAreaNode(self, node: TradeAreaNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        lines = [
            f"# TradeArea: create trade area polygon (radius={node.radius} {node.radius_units}, rings={node.ring_count})",
            "# Requires: import mosaic; mosaic.enable_mosaic(spark)",
            f'{out_var} = {inp}.withColumn("{node.output_field}", '
            f'F.expr("st_buffer({node.input_field}, {node.radius})"))',
        ]
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=[
                f"TradeAreaNode (node {node.node_id}): requires Databricks Mosaic library (st_buffer); multi-ring trade areas need manual adjustment"
            ],
        )

    def _generate_MakeGridNode(self, node: MakeGridNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        # Convert grid_size to an approximate H3 resolution
        # H3 resolutions: ~1km = res 7, ~5km = res 5, ~10km = res 4
        resolution = 7  # default
        lines = [
            f"# Grid generation using H3 polyfill (grid_size={node.grid_size} {node.grid_units})",
            "# Requires: h3-pyspark or Databricks Mosaic H3 functions",
            f'{out_var} = {inp}.selectExpr("explode(h3_polyfill({node.extent_field}, {resolution})) as {node.output_field}")',
        ]
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=[
                f"MakeGridNode (node {node.node_id}): requires H3 library; adjust resolution ({resolution}) based on grid_size={node.grid_size} {node.grid_units}"
            ],
        )

    # -- Predictive / ML nodes ----------------------------------------------

    def _generate_PredictiveModelNode(self, node: PredictiveModelNode, input_vars: dict[str, str]) -> NodeCodeResult:
        """Generic handler for all predictive/ML tool types — emits passthrough with TODO."""
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"
        tool = node.model_type or node.original_tool_type
        parts = [f"target='{node.target_field}'"] if node.target_field else []
        if node.feature_fields:
            parts.append(f"features={node.feature_fields!r}")
        for k, v in sorted(node.config.items()):
            parts.append(f"{k}={v!r}")
        params = ", ".join(parts)
        lines = [
            f"# {tool}: {params}" if params else f"# {tool}: no configuration extracted",
            "# TODO: Convert to Spark MLlib or equivalent — manual implementation required",
            f"{out_var} = {inp}  # passthrough placeholder",
        ]
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=[f"{tool} (node {node.node_id}): requires manual conversion to Spark MLlib"],
        )

    # -- Special nodes ------------------------------------------------------

    def _generate_DynamicRenameNode(self, node: DynamicRenameNode, input_vars: dict[str, str]) -> NodeCodeResult:
        inp = self._get_single_input(input_vars)
        out_var = f"df_{node.node_id}"

        if node.rename_mode == "FirstRow":
            lines = [
                "# DynamicRename (FirstRow): use first row values as new column names",
                f"_first_row_{node.node_id} = {inp}.first()",
                f"{out_var} = {inp}.toDF(*[str(v) for v in _first_row_{node.node_id}])",
                f"{out_var} = {out_var}.subtract({inp}.limit(1))  # remove the header row",
            ]
        else:
            lines = [
                f"# TODO: DynamicRename mode '{node.rename_mode}' — manual conversion required",
                f"{out_var} = {inp}  # passthrough placeholder",
            ]

        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=(
                [f"DynamicRename node {node.node_id} ({node.rename_mode} mode): manual PySpark rewrite needed"]
                if node.rename_mode != "FirstRow"
                else []
            ),
        )

    def _generate_DirectoryNode(self, node: DirectoryNode, input_vars: dict[str, str]) -> NodeCodeResult:
        out_var = f"df_{node.node_id}"
        path = node.directory_path or "/mnt/data"
        pattern = node.file_pattern or "*"
        recursive = str(node.include_subdirs).lower()

        lines = [
            f"# Directory listing: {path} (pattern={pattern}, recursive={recursive})",
            f"_files_{node.node_id} = dbutils.fs.ls('{path}')",
        ]
        if pattern != "*":
            lines.append(
                f"_files_{node.node_id} = [f for f in _files_{node.node_id} if f.name.endswith('{pattern.lstrip('*')}')]"
            )
        lines.extend(
            [
                f"{out_var} = spark.createDataFrame(",
                f"    [(f.path, f.name, f.size) for f in _files_{node.node_id}],",
                '    ["FullPath", "FileName", "FileSize"]',
                ")",
            ]
        )
        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": out_var},
            warnings=[],
        )

    def _unsupported_passthrough(
        self, node: IRNode, input_vars: dict[str, str], label: str | None = None
    ) -> NodeCodeResult:
        """Emit a concise passthrough for unsupported node types.

        Instead of emitting a redundant ``df_N = df_M`` identity assignment,
        the input variable is returned directly as the output so downstream
        nodes reference the original DataFrame without an indirection chain.
        """
        inp = self._get_single_input(input_vars)
        tool = label or node.original_tool_type or node.original_plugin_name or type(node).__name__
        reason = getattr(node, "unsupported_reason", None) or "No auto-conversion available"

        if self.config.verbose_unsupported:
            lines = [
                f"# UNSUPPORTED: {tool}",
                f"# Reason: {reason}",
                "# TODO: Manual conversion required.",
            ]
        else:
            lines = [f"# {tool}: manual conversion required"]

        return NodeCodeResult(
            code_lines=lines,
            output_vars={"Output": inp},  # reuse input var — no identity assignment
            warnings=[f"Unsupported node {node.node_id} ({tool}): {reason}"],
        )

    def _generate_UnsupportedNode(self, node: UnsupportedNode, input_vars: dict[str, str]) -> NodeCodeResult:
        return self._unsupported_passthrough(node, input_vars)

    def _generate_CommentNode(self, node: CommentNode, input_vars: dict[str, str]) -> NodeCodeResult:
        # Handled specially in generate() but provide fallback
        lines = [f"# {node.comment_text}"] if node.comment_text else []
        return NodeCodeResult(code_lines=lines, output_vars={})

    # _map_file_format and _get_single_input inherited from CodeGenerator base class
