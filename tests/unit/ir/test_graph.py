"""Unit tests for the WorkflowDAG."""

from __future__ import annotations

import networkx as nx
import pytest

from a2d.ir.graph import EdgeInfo, WorkflowDAG
from a2d.ir.nodes import (
    FilterNode,
    FormulaNode,
    ReadNode,
    SelectNode,
    SortNode,
    WriteNode,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_read(node_id: int) -> ReadNode:
    return ReadNode(node_id=node_id, original_tool_type="Input")


def _make_filter(node_id: int) -> FilterNode:
    return FilterNode(node_id=node_id, original_tool_type="Filter", expression="[x] > 1")


def _make_write(node_id: int) -> WriteNode:
    return WriteNode(node_id=node_id, original_tool_type="Output")


def _make_formula(node_id: int) -> FormulaNode:
    return FormulaNode(node_id=node_id, original_tool_type="Formula")


def _make_select(node_id: int) -> SelectNode:
    return SelectNode(node_id=node_id, original_tool_type="Select")


def _make_sort(node_id: int) -> SortNode:
    return SortNode(node_id=node_id, original_tool_type="Sort")


def _build_linear_dag() -> WorkflowDAG:
    """Read(1) -> Filter(2) -> Write(3)"""
    dag = WorkflowDAG()
    dag.add_node(_make_read(1))
    dag.add_node(_make_filter(2))
    dag.add_node(_make_write(3))
    dag.add_edge(1, 2)
    dag.add_edge(2, 3)
    return dag


# ---------------------------------------------------------------------------
# Tests: add_nodes_and_edges
# ---------------------------------------------------------------------------


class TestAddNodesAndEdges:
    """Test basic graph construction."""

    def test_add_single_node(self) -> None:
        dag = WorkflowDAG()
        dag.add_node(_make_read(1))
        assert dag.node_count == 1
        assert dag.edge_count == 0

    def test_add_edge(self) -> None:
        dag = _build_linear_dag()
        assert dag.node_count == 3
        assert dag.edge_count == 2

    def test_get_node(self) -> None:
        dag = _build_linear_dag()
        node = dag.get_node(2)
        assert isinstance(node, FilterNode)
        assert node.node_id == 2

    def test_get_node_missing(self) -> None:
        dag = WorkflowDAG()
        with pytest.raises(KeyError):
            dag.get_node(999)

    def test_add_edge_missing_source(self) -> None:
        dag = WorkflowDAG()
        dag.add_node(_make_read(1))
        with pytest.raises(KeyError, match="Source node 99"):
            dag.add_edge(99, 1)

    def test_add_edge_missing_target(self) -> None:
        dag = WorkflowDAG()
        dag.add_node(_make_read(1))
        with pytest.raises(KeyError, match="Target node 99"):
            dag.add_edge(1, 99)

    def test_edge_info(self) -> None:
        dag = WorkflowDAG()
        dag.add_node(_make_read(1))
        dag.add_node(_make_filter(2))
        dag.add_edge(1, 2, origin_anchor="Output", destination_anchor="Input")
        info = dag.get_edge_info(1, 2)
        assert isinstance(info, EdgeInfo)
        assert info.origin_anchor == "Output"
        assert info.destination_anchor == "Input"
        assert info.is_wireless is False

    def test_edge_info_missing(self) -> None:
        dag = _build_linear_dag()
        with pytest.raises(KeyError):
            dag.get_edge_info(1, 3)  # no direct edge


# ---------------------------------------------------------------------------
# Tests: topological_order
# ---------------------------------------------------------------------------


class TestTopologicalOrder:
    """Test topological sorting."""

    def test_linear_order(self) -> None:
        dag = _build_linear_dag()
        order = dag.topological_order()
        ids = [n.node_id for n in order]
        assert ids == [1, 2, 3]

    def test_diamond_order(self) -> None:
        """
        1 -> 2
        1 -> 3
        2 -> 4
        3 -> 4
        """
        dag = WorkflowDAG()
        dag.add_node(_make_read(1))
        dag.add_node(_make_filter(2))
        dag.add_node(_make_formula(3))
        dag.add_node(_make_write(4))
        dag.add_edge(1, 2)
        dag.add_edge(1, 3)
        dag.add_edge(2, 4)
        dag.add_edge(3, 4)

        order = dag.topological_order()
        ids = [n.node_id for n in order]
        # Node 1 must come first, node 4 must come last
        assert ids[0] == 1
        assert ids[-1] == 4
        # 2 and 3 must come before 4
        assert ids.index(2) < ids.index(4)
        assert ids.index(3) < ids.index(4)


# ---------------------------------------------------------------------------
# Tests: source and sink nodes
# ---------------------------------------------------------------------------


class TestSourceAndSinkNodes:
    """Test identification of entry/exit points."""

    def test_source_nodes(self) -> None:
        dag = _build_linear_dag()
        sources = dag.get_source_nodes()
        assert len(sources) == 1
        assert sources[0].node_id == 1

    def test_sink_nodes(self) -> None:
        dag = _build_linear_dag()
        sinks = dag.get_sink_nodes()
        assert len(sinks) == 1
        assert sinks[0].node_id == 3

    def test_multiple_sources(self) -> None:
        dag = WorkflowDAG()
        dag.add_node(_make_read(1))
        dag.add_node(_make_read(2))
        dag.add_node(_make_write(3))
        dag.add_edge(1, 3)
        dag.add_edge(2, 3)

        sources = dag.get_source_nodes()
        source_ids = {n.node_id for n in sources}
        assert source_ids == {1, 2}

    def test_multiple_sinks(self) -> None:
        dag = WorkflowDAG()
        dag.add_node(_make_read(1))
        dag.add_node(_make_write(2))
        dag.add_node(_make_write(3))
        dag.add_edge(1, 2)
        dag.add_edge(1, 3)

        sinks = dag.get_sink_nodes()
        sink_ids = {n.node_id for n in sinks}
        assert sink_ids == {2, 3}


# ---------------------------------------------------------------------------
# Tests: connected components
# ---------------------------------------------------------------------------


class TestConnectedComponents:
    """Test detection of disconnected sub-graphs."""

    def test_single_component(self) -> None:
        dag = _build_linear_dag()
        components = dag.get_connected_components()
        assert len(components) == 1
        assert components[0] == {1, 2, 3}

    def test_two_components(self) -> None:
        dag = WorkflowDAG()
        # Component 1: 1 -> 2
        dag.add_node(_make_read(1))
        dag.add_node(_make_write(2))
        dag.add_edge(1, 2)

        # Component 2: 3 -> 4
        dag.add_node(_make_read(3))
        dag.add_node(_make_write(4))
        dag.add_edge(3, 4)

        components = dag.get_connected_components()
        assert len(components) == 2
        component_sets = [frozenset(c) for c in components]
        assert frozenset({1, 2}) in component_sets
        assert frozenset({3, 4}) in component_sets

    def test_isolated_node(self) -> None:
        dag = WorkflowDAG()
        dag.add_node(_make_read(1))
        dag.add_node(_make_write(2))
        dag.add_edge(1, 2)
        dag.add_node(_make_filter(3))  # isolated

        components = dag.get_connected_components()
        assert len(components) == 2


# ---------------------------------------------------------------------------
# Tests: cycle detection (via validate)
# ---------------------------------------------------------------------------


class TestCycleDetection:
    """Test that cycles are detected by validate()."""

    def test_no_cycle(self) -> None:
        dag = _build_linear_dag()
        issues = dag.validate()
        assert not any("Cycle" in i for i in issues)

    def test_cycle_detected(self) -> None:
        dag = WorkflowDAG()
        dag.add_node(_make_read(1))
        dag.add_node(_make_filter(2))
        dag.add_node(_make_formula(3))
        dag.add_edge(1, 2)
        dag.add_edge(2, 3)
        dag.add_edge(3, 1)  # creates a cycle

        issues = dag.validate()
        assert any("Cycle" in i for i in issues)

    def test_topological_sort_raises_on_cycle(self) -> None:
        dag = WorkflowDAG()
        dag.add_node(_make_read(1))
        dag.add_node(_make_filter(2))
        dag.add_edge(1, 2)
        dag.add_edge(2, 1)

        with pytest.raises(nx.NetworkXUnfeasible):
            dag.topological_order()


# ---------------------------------------------------------------------------
# Tests: predecessors and successors
# ---------------------------------------------------------------------------


class TestPredecessorsAndSuccessors:
    """Test querying neighboring nodes."""

    def test_predecessors(self) -> None:
        dag = _build_linear_dag()
        preds = dag.get_predecessors(2)
        assert len(preds) == 1
        assert preds[0].node_id == 1

    def test_successors(self) -> None:
        dag = _build_linear_dag()
        succs = dag.get_successors(2)
        assert len(succs) == 1
        assert succs[0].node_id == 3

    def test_source_has_no_predecessors(self) -> None:
        dag = _build_linear_dag()
        assert dag.get_predecessors(1) == []

    def test_sink_has_no_successors(self) -> None:
        dag = _build_linear_dag()
        assert dag.get_successors(3) == []

    def test_multiple_predecessors(self) -> None:
        dag = WorkflowDAG()
        dag.add_node(_make_read(1))
        dag.add_node(_make_read(2))
        dag.add_node(_make_filter(3))
        dag.add_edge(1, 3)
        dag.add_edge(2, 3)

        preds = dag.get_predecessors(3)
        pred_ids = {p.node_id for p in preds}
        assert pred_ids == {1, 2}

    def test_multiple_successors(self) -> None:
        dag = WorkflowDAG()
        dag.add_node(_make_read(1))
        dag.add_node(_make_write(2))
        dag.add_node(_make_write(3))
        dag.add_edge(1, 2)
        dag.add_edge(1, 3)

        succs = dag.get_successors(1)
        succ_ids = {s.node_id for s in succs}
        assert succ_ids == {2, 3}


# ---------------------------------------------------------------------------
# Tests: validate (disconnected warning)
# ---------------------------------------------------------------------------


class TestValidate:
    """Test the full validate method."""

    def test_valid_graph(self) -> None:
        dag = _build_linear_dag()
        issues = dag.validate()
        assert issues == []

    def test_disconnected_warning(self) -> None:
        dag = WorkflowDAG()
        dag.add_node(_make_read(1))
        dag.add_node(_make_write(2))
        dag.add_edge(1, 2)
        dag.add_node(_make_filter(3))  # disconnected

        issues = dag.validate()
        assert any("disconnected" in i for i in issues)

    def test_repr(self) -> None:
        dag = _build_linear_dag()
        assert "nodes=3" in repr(dag)
        assert "edges=2" in repr(dag)

    def test_all_nodes_iterator(self) -> None:
        dag = _build_linear_dag()
        all_ids = {n.node_id for n in dag.all_nodes()}
        assert all_ids == {1, 2, 3}

    def test_all_node_ids(self) -> None:
        dag = _build_linear_dag()
        assert set(dag.all_node_ids()) == {1, 2, 3}
