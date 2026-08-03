"""Tests for the AI/BI (Lakeview) dashboard reporting bridge."""

from __future__ import annotations

import json

from a2d.bridges.reporting import build_dashboard_spec
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import BrowseNode, ChartNode, ReportNode, WriteNode


def _dag(*nodes):
    dag = WorkflowDAG()
    for n in nodes:
        dag.add_node(n)
    return dag


class TestBuildDashboardSpec:
    def test_empty_when_no_reporting_nodes(self):
        dag = _dag(WriteNode(node_id=1, table_name="t"))
        spec = build_dashboard_spec(dag, "wf")
        assert spec.widget_count == 0

    def test_chart_becomes_chart_widget(self):
        dag = _dag(
            ChartNode(node_id=2, chart_type="bar", x_field="region", y_field="rev", title="Rev"),
        )
        spec = build_dashboard_spec(dag, "wf")
        assert spec.widget_count == 1
        w = spec.widgets[0]
        assert w.widget_type == "bar"
        assert w.x_field == "region"
        assert w.y_field == "rev"

    def test_report_and_browse_become_tables(self):
        dag = _dag(
            ReportNode(node_id=1, report_type="table"),
            BrowseNode(node_id=2),
        )
        spec = build_dashboard_spec(dag, "wf")
        assert spec.widget_count == 2
        assert all(w.widget_type == "table" for w in spec.widgets)

    def test_upstream_write_table_used_as_dataset(self):
        dag = _dag(
            WriteNode(node_id=1, table_name="main.sales.summary"),
            ChartNode(node_id=2, chart_type="line", x_field="d", y_field="v"),
        )
        dag.add_edge(1, 2)
        spec = build_dashboard_spec(dag, "wf")
        assert spec.datasets["ds_2"] == "main.sales.summary"

    def test_unknown_chart_type_falls_back_to_bar(self):
        dag = _dag(ChartNode(node_id=1, chart_type="donut3d", x_field="a", y_field="b"))
        spec = build_dashboard_spec(dag, "wf")
        assert spec.widgets[0].widget_type == "bar"


class TestLakeviewOutput:
    def test_valid_json_structure(self):
        dag = _dag(
            WriteNode(node_id=1, table_name="cat.sch.tbl"),
            ChartNode(node_id=2, chart_type="bar", x_field="x", y_field="y", title="T"),
        )
        dag.add_edge(1, 2)
        spec = build_dashboard_spec(dag, "my_dash")
        doc = json.loads(spec.to_json())
        assert doc["displayName"] == "my_dash"
        assert len(doc["datasets"]) == 1
        assert doc["datasets"][0]["queryLines"] == ["SELECT * FROM cat.sch.tbl"]
        page = doc["pages"][0]
        assert len(page["layout"]) == 1
        widget = page["layout"][0]["widget"]
        assert widget["spec"]["widgetType"] == "bar"
        assert widget["spec"]["encodings"]["x"]["fieldName"] == "x"

    def test_table_widget_spec(self):
        dag = _dag(BrowseNode(node_id=1))
        spec = build_dashboard_spec(dag, "d")
        doc = spec.to_lakeview()
        widget = doc["pages"][0]["layout"][0]["widget"]
        assert widget["spec"]["widgetType"] == "table"
        assert widget["queries"][0]["query"]["disaggregated"] is True
