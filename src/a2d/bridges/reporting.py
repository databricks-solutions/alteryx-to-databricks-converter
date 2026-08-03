"""Reporting bridge: build a Databricks AI/BI (Lakeview) dashboard from IR.

Alteryx reporting tools (Chart, Table/Layout/Render, Browse) currently convert
to a bare ``display()`` call. This bridge collects those nodes across a workflow
and emits a Databricks **AI/BI (Lakeview) dashboard** JSON spec — a real
dashboard artifact (one dataset + one widget per reporting node) that can be
imported into a workspace, instead of a throwaway preview.

The spec follows the Lakeview ``.lvdash.json`` shape (datasets + pages with
widgets). It is a pure function of the IR: deterministic and offline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import BrowseNode, ChartNode, IRNode, ReportNode

# Alteryx chart types → Lakeview widget spec "version"/encoding kind.
_CHART_WIDGET = {
    "bar": "bar",
    "column": "bar",
    "line": "line",
    "scatter": "scatter",
    "pie": "pie",
    "area": "area",
}


@dataclass
class DashboardWidget:
    """One dashboard widget derived from a reporting node."""

    name: str
    widget_type: str  # "bar" | "line" | "table" | ...
    title: str
    dataset_name: str
    x_field: str = ""
    y_field: str = ""
    series_fields: list[str] = field(default_factory=list)


@dataclass
class DashboardSpec:
    """A Lakeview dashboard spec assembled from a workflow's reporting nodes."""

    display_name: str
    widgets: list[DashboardWidget] = field(default_factory=list)
    # dataset_name -> the table/query the widget reads (best-effort from upstream).
    datasets: dict[str, str] = field(default_factory=dict)

    @property
    def widget_count(self) -> int:
        return len(self.widgets)

    def to_lakeview(self) -> dict:
        """Render the Lakeview ``.lvdash.json`` document."""
        datasets = [
            {
                "name": ds_name,
                "displayName": ds_name,
                "queryLines": [f"SELECT * FROM {source}"],
            }
            for ds_name, source in sorted(self.datasets.items())
        ]

        layout = []
        for i, w in enumerate(self.widgets):
            layout.append(
                {
                    "widget": {
                        "name": w.name,
                        "queries": [
                            {
                                "name": f"{w.name}_query",
                                "query": {
                                    "datasetName": w.dataset_name,
                                    "fields": _widget_fields(w),
                                    "disaggregated": w.widget_type == "table",
                                },
                            }
                        ],
                        "spec": _widget_spec(w),
                    },
                    "position": {"x": (i % 2) * 3, "y": (i // 2) * 4, "width": 3, "height": 4},
                }
            )

        return {
            "displayName": self.display_name,
            "datasets": datasets,
            "pages": [
                {
                    "name": "page_1",
                    "displayName": "Overview",
                    "layout": layout,
                }
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_lakeview(), indent=2) + "\n"


def _widget_fields(w: DashboardWidget) -> list[dict]:
    fields: list[dict] = []
    if w.x_field:
        fields.append({"name": w.x_field, "expression": f"`{w.x_field}`"})
    if w.y_field:
        fields.append({"name": w.y_field, "expression": f"`{w.y_field}`"})
    for s in w.series_fields:
        fields.append({"name": s, "expression": f"`{s}`"})
    return fields


def _widget_spec(w: DashboardWidget) -> dict:
    if w.widget_type == "table":
        return {"version": 1, "widgetType": "table"}
    spec: dict = {"version": 3, "widgetType": w.widget_type, "encodings": {}}
    if w.x_field:
        spec["encodings"]["x"] = {"fieldName": w.x_field, "scale": {"type": "categorical"}}
    if w.y_field:
        spec["encodings"]["y"] = {"fieldName": w.y_field, "scale": {"type": "quantitative"}}
    if w.series_fields:
        spec["encodings"]["color"] = {"fieldName": w.series_fields[0], "scale": {"type": "categorical"}}
    return spec


def _upstream_source(node: IRNode, dag: WorkflowDAG) -> str:
    """Best-effort table/view name feeding a reporting node.

    Uses a WriteNode's table name if one is directly upstream, else a generic
    placeholder keyed by node id (the user points it at the right table).
    """
    from a2d.ir.nodes import WriteNode

    for pred in dag.get_predecessors(node.node_id):
        if isinstance(pred, WriteNode) and pred.table_name:
            return pred.table_name
    return f"<source_for_node_{node.node_id}>"


def build_dashboard_spec(dag: WorkflowDAG, display_name: str) -> DashboardSpec:
    """Assemble a dashboard spec from a workflow's Chart / Report / Browse nodes."""
    spec = DashboardSpec(display_name=display_name)

    reporting_nodes = [n for n in dag.all_nodes() if isinstance(n, ChartNode | ReportNode | BrowseNode)]
    for node in sorted(reporting_nodes, key=lambda n: n.node_id):
        dataset_name = f"ds_{node.node_id}"
        spec.datasets[dataset_name] = _upstream_source(node, dag)

        if isinstance(node, ChartNode):
            widget = DashboardWidget(
                name=f"chart_{node.node_id}",
                widget_type=_CHART_WIDGET.get(node.chart_type.lower(), "bar"),
                title=node.title or f"Chart {node.node_id}",
                dataset_name=dataset_name,
                x_field=node.x_field,
                y_field=node.y_field,
                series_fields=list(node.series_fields),
            )
        else:
            # ReportNode / BrowseNode → table widget.
            title = getattr(node, "title", "") or f"Table {node.node_id}"
            widget = DashboardWidget(
                name=f"table_{node.node_id}",
                widget_type="table",
                title=title,
                dataset_name=dataset_name,
            )
        spec.widgets.append(widget)

    return spec
