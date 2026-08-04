"""Coverage for the P2 robustness fixes.

Each of these guards a case where the previous behaviour degraded silently:
defaulting a mistyped connection to the wrong catalog, recursing without bound on
hostile XML, or indexing past the cluster-tier list.
"""

from __future__ import annotations

import logging

import pytest
from lxml import etree

from a2d.advisor.cost import _TIERS, CostPerformanceAdvisor
from a2d.config import ConversionConfig
from a2d.connections import ConnectionMapping, ConnectionMappingConfig
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import ReadNode, WriteNode
from a2d.utils.xml_helpers import MAX_XML_DEPTH, element_to_dict


class TestUnmappedConnectionWarns:
    def test_unmapped_name_logs_a_warning(self, caplog):
        cfg = ConnectionMappingConfig(default_catalog="main", default_schema="default")
        with caplog.at_level(logging.WARNING):
            resolved = cfg.resolve("DataWareHouse", "orders")

        # Still resolves (behaviour unchanged) …
        assert resolved == "main.default.orders"
        # … but the user is told the mapping didn't apply.
        assert any("has no mapping" in r.getMessage() for r in caplog.records)

    def test_mapped_name_is_silent(self, caplog):
        cfg = ConnectionMappingConfig(
            mappings={"DW": ConnectionMapping(alteryx_name="DW", catalog="c", schema="s")},
        )
        with caplog.at_level(logging.WARNING):
            cfg.resolve("DW", "orders")

        assert not caplog.records

    def test_warns_only_once_per_name(self, caplog):
        """A connection used by twenty nodes shouldn't log twenty times."""
        cfg = ConnectionMappingConfig()
        with caplog.at_level(logging.WARNING):
            for _ in range(5):
                cfg.resolve("Missing", "t")

        assert len([r for r in caplog.records if "has no mapping" in r.getMessage()]) == 1

    def test_empty_connection_name_does_not_warn(self, caplog):
        cfg = ConnectionMappingConfig()
        with caplog.at_level(logging.WARNING):
            cfg.resolve("", "t")

        assert not caplog.records


class TestXmlDepthLimit:
    def _nested(self, depth: int) -> etree._Element:
        root = etree.Element("r")
        cur = root
        for i in range(depth):
            cur = etree.SubElement(cur, f"n{i}")
        cur.text = "leaf"
        return root

    def test_normal_nesting_is_unaffected(self):
        """Real Alteryx config nests only a few levels."""
        result = element_to_dict(self._nested(5))
        assert isinstance(result, dict)
        assert "#truncated" not in str(result)[:50]

    def test_excessive_nesting_is_truncated_not_crashed(self):
        # Well past the limit; previously this recursed unbounded.
        result = element_to_dict(self._nested(MAX_XML_DEPTH + 50))
        assert "#truncated" in str(result)

    def test_truncation_happens_at_the_limit(self, caplog):
        with caplog.at_level(logging.WARNING):
            element_to_dict(self._nested(MAX_XML_DEPTH + 5))
        assert any("XML nesting exceeded" in str(r.msg) for r in caplog.records)


class TestClusterTierClamp:
    def test_extreme_workload_stays_within_tier_list(self):
        """A very large DAG must not index past _TIERS."""
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=0, original_tool_type="Input"))
        prev = 0
        for i in range(1, 60):
            dag.add_node(WriteNode(node_id=i, original_tool_type="Output"))
            dag.add_edge(prev, i)
            prev = i

        report = CostPerformanceAdvisor().analyze(dag, ConversionConfig(), workflow_name="big")

        # _TIERS is a list of dicts; the chosen tier must be one of them.
        assert report.cluster.tier in [entry["tier"] for entry in _TIERS]
        assert report.cluster.workers >= 0

    @pytest.mark.parametrize("node_count", [1, 3, 10, 30])
    def test_tier_selection_never_raises(self, node_count):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=0, original_tool_type="Input"))
        for i in range(1, node_count):
            dag.add_node(WriteNode(node_id=i, original_tool_type="Output"))
            dag.add_edge(i - 1, i)

        report = CostPerformanceAdvisor().analyze(dag, ConversionConfig(), workflow_name="wf")
        assert report.cluster.tier
