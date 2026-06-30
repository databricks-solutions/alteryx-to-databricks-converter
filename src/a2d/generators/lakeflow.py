"""Lakeflow Declarative Pipelines SQL generator for Databricks Lakeflow Designer.

Walks a :class:`~a2d.ir.graph.WorkflowDAG` and produces individual
``CREATE OR REFRESH MATERIALIZED VIEW`` / ``CREATE OR REFRESH STREAMING TABLE``
statements. Each statement becomes one visual node in the Lakeflow Designer canvas.

Inherits all ~60 node-type SQL body handlers from :class:`SQLGenerator` and only
overrides the top-level wrapping (individual views vs. CTE chain) and upstream
reference resolution (``LIVE.`` prefix for inter-view dependencies).
"""

from __future__ import annotations

import json
import logging

from a2d.expressions.base_translator import BaseTranslationError
from a2d.generators.base import GeneratedFile, GeneratedOutput
from a2d.generators.sql import SQLGenerator, _cte_name
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    AutoFieldNode,
    BrowseNode,
    CloudStorageNode,
    CommentNode,
    DynamicInputNode,
    FilterNode,
    ReadNode,
    UnsupportedNode,
    WorkflowControlNode,
)

logger = logging.getLogger("a2d.generators.lakeflow")

# Node types whose file-based sources should use STREAMING TABLE
_STREAMING_SOURCE_TYPES = (ReadNode, CloudStorageNode, DynamicInputNode)

# Prefix for inter-view references in Lakeflow Declarative Pipelines
_LIVE_PREFIX = "LIVE."


class LakeflowGenerator(SQLGenerator):
    """Generate Lakeflow Declarative Pipelines SQL for Databricks Lakeflow Designer."""

    # Passthrough types: skip statement, forward predecessor's view name
    _PASSTHROUGH_TYPES = (AutoFieldNode, BrowseNode, WorkflowControlNode)

    def generate(self, dag: WorkflowDAG, workflow_name: str = "workflow") -> GeneratedOutput:
        ordered_nodes = dag.topological_order()
        warnings: list[str] = []
        view_map: dict[int, str] = {}  # node_id -> view name
        # Separate map for filter fan-out: (filter_node_id, successor_node_id) -> false view name
        self._fanout_map: dict[tuple[int, int], str] = {}
        statements: list[str] = []
        node_count = 0
        unsupported_count = 0

        for node in ordered_nodes:
            if isinstance(node, CommentNode):
                statements.append(f"-- {node.comment_text or ''}")
                continue

            # Skip passthrough nodes: forward the predecessor's view name
            if isinstance(node, self._PASSTHROUGH_TYPES):
                input_views = self._resolve_input_views(node.node_id, dag, view_map)
                prev = self._get_single_input(input_views) if input_views else None
                if prev:
                    # Strip LIVE. prefix to store the bare view name
                    bare = prev[len(_LIVE_PREFIX) :] if prev.startswith(_LIVE_PREFIX) else prev
                    view_map[node.node_id] = bare
                    node_count += 1
                    continue

            name = _cte_name(node)
            view_map[node.node_id] = name

            # Handle Filter fan-out: True/False branches produce two views
            if isinstance(node, FilterNode):
                outgoing = dag.get_outgoing_anchors(node.node_id)
                has_true = "True" in outgoing or "Output" in outgoing
                has_false = "False" in outgoing

                if has_true and has_false:
                    stmts, step_warnings = self._generate_filter_fanout(node, dag, view_map, name)
                    warnings.extend(step_warnings)
                    statements.extend(stmts)
                    node_count += 1
                    continue

            input_views = self._resolve_input_views(node.node_id, dag, view_map)
            sql_body, step_warnings = self._generate_cte_body(node, input_views)
            warnings.extend(step_warnings)

            stmt_type = self._statement_type(node)
            annotation = node.annotation or node.original_tool_type or type(node).__name__
            comment = f"-- Step {node.node_id}: {annotation}"
            statement = f"{comment}\n{stmt_type} {name} AS\n{sql_body};\n"
            statements.append(statement)

            node_count += 1
            if isinstance(node, UnsupportedNode):
                unsupported_count += 1

        # Build full output
        self.metadata["stats"] = {
            "total_nodes": node_count,
            "supported_nodes": node_count - unsupported_count,
            "unsupported_nodes": unsupported_count,
            "warnings": len(warnings),
        }

        meta_header = self._build_header_lines(workflow_name, "--")
        header = "\n".join(meta_header) + "\n"
        header += "-- Format: Lakeflow Declarative Pipelines (LDP) SQL\n\n"

        sql = header + "\n".join(statements) + "\n"

        # Append footer
        footer_lines = self._build_footer_lines(sql, "--")
        sql += "\n" + "\n".join(footer_lines) + "\n"

        files = [
            GeneratedFile(
                filename=f"{workflow_name}_lakeflow.sql",
                content=sql,
                file_type="sql",
            ),
        ]

        # Generate companion pipeline JSON
        pipeline_json = self._generate_pipeline_json(workflow_name)
        files.append(
            GeneratedFile(
                filename=f"{workflow_name}_lakeflow_pipeline.json",
                content=pipeline_json,
                file_type="json",
            )
        )

        stats = {
            "total_nodes": node_count,
            "supported_nodes": node_count - unsupported_count,
            "unsupported_nodes": unsupported_count,
            "total_views": len([s for s in statements if "CREATE OR REFRESH" in s]),
            "warnings": len(warnings),
        }

        return GeneratedOutput(files=files, warnings=warnings, stats=stats)

    # -- Overrides ----------------------------------------------------------

    def _resolve_input_views(self, node_id: int, dag: WorkflowDAG, view_map: dict[int, str]) -> dict[str, str]:
        """Map destination anchors to upstream view names with LIVE. prefix."""
        raw = self._resolve_input_ctes(node_id, dag, view_map)
        return {anchor: f"{_LIVE_PREFIX}{name}" for anchor, name in raw.items()}

    def _statement_type(self, node) -> str:
        """Determine whether a node is a STREAMING TABLE or MATERIALIZED VIEW."""
        if isinstance(node, _STREAMING_SOURCE_TYPES) and self._is_file_source(node):
            return "CREATE OR REFRESH STREAMING TABLE"
        return "CREATE OR REFRESH MATERIALIZED VIEW"

    # -- Helpers ------------------------------------------------------------

    @staticmethod
    def _is_file_source(node) -> bool:
        """Check if a source node reads from files (vs. database)."""
        if isinstance(node, ReadNode):
            return node.source_type != "database"
        if isinstance(node, CloudStorageNode):
            return node.direction == "input"
        return isinstance(node, DynamicInputNode)

    def _generate_filter_fanout(
        self,
        node: FilterNode,
        dag: WorkflowDAG,
        view_map: dict[int, str],
        base_name: str,
    ) -> tuple[list[str], list[str]]:
        """Generate two views for a filter with both True and False branches."""
        warnings: list[str] = []
        stmts: list[str] = []
        input_views = self._resolve_input_views(node.node_id, dag, view_map)
        inp = self._get_single_input(input_views)

        if not node.expression or not node.expression.strip():
            warnings.append(f"Filter node {node.node_id} has no expression — returning all rows for both branches")
            expr = "TRUE"
        else:
            try:
                expr = self._translator.translate_string(node.expression)
            except BaseTranslationError:
                expr = node.expression
                warnings.append(f"Lakeflow filter expression fallback for node {node.node_id}")

        true_name = f"{base_name}_true"
        false_name = f"{base_name}_false"

        annotation = node.annotation or "Filter"

        stmts.append(
            f"-- Step {node.node_id}: {annotation} (True branch)\n"
            f"CREATE OR REFRESH MATERIALIZED VIEW {true_name} AS\n"
            f"SELECT * FROM {inp} WHERE {expr};\n"
        )
        stmts.append(
            f"-- Step {node.node_id}: {annotation} (False branch)\n"
            f"CREATE OR REFRESH MATERIALIZED VIEW {false_name} AS\n"
            f"SELECT * FROM {inp} WHERE NOT ({expr});\n"
        )

        # Store True branch as default in view_map
        view_map[node.node_id] = true_name

        # Record False branch mapping for downstream successor resolution
        for succ in dag.get_successors(node.node_id):
            edge_info = dag.get_edge_info(node.node_id, succ.node_id)
            if edge_info.origin_anchor == "False":
                self._fanout_map[(node.node_id, succ.node_id)] = false_name

        return stmts, warnings

    def _resolve_input_ctes(self, node_id: int, dag: WorkflowDAG, cte_map: dict[int, str]) -> dict[str, str]:
        """Map destination anchors to upstream view names.

        Overrides the parent to handle filter fan-out: if a predecessor's
        outgoing anchor is "False", resolve to the corresponding fan-out
        view name stored in ``_fanout_map``.
        """
        result: dict[str, str] = {}
        preds = dag.get_predecessors(node_id)
        for pred in preds:
            edge_info = dag.get_edge_info(pred.node_id, node_id)
            dest_anchor = edge_info.destination_anchor
            origin_anchor = edge_info.origin_anchor

            # Check for filter fan-out mapping (False branch)
            fanout_key = (pred.node_id, node_id)
            if fanout_key in self._fanout_map:
                result[dest_anchor] = self._fanout_map[fanout_key]
            elif origin_anchor == "False" and isinstance(pred, FilterNode):
                # Only derive _false view name when fan-out actually occurred
                # (i.e., the view_map entry ends with _true, set by _generate_filter_fanout)
                base = cte_map.get(pred.node_id, f"step_{pred.node_id}_unknown")
                if base.endswith("_true"):
                    result[dest_anchor] = base[:-5] + "_false"
                else:
                    # Single-branch filter: use the base name directly
                    result[dest_anchor] = base
            else:
                result[dest_anchor] = cte_map.get(pred.node_id, f"step_{pred.node_id}_unknown")
        return result

    def _generate_pipeline_json(self, workflow_name: str) -> str:
        """Generate companion Lakeflow pipeline configuration JSON."""
        pipeline_config = {
            "name": f"a2d_{workflow_name}_lakeflow",
            "catalog": self.config.catalog_name,
            "target": self.config.schema_name,
            "libraries": [{"file": {"path": f"/Workspace/Shared/a2d/{workflow_name}_lakeflow.sql"}}],
            "clusters": [
                {
                    "label": "default",
                    "autoscale": {
                        "min_workers": 1,
                        "max_workers": 4,
                        "mode": "ENHANCED",
                    },
                }
            ],
            "channel": "CURRENT",
            "development": True,
        }
        return json.dumps(pipeline_config, indent=2) + "\n"
