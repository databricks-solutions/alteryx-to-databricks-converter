"""Directed acyclic graph (DAG) for an Alteryx workflow's IR representation.

Backed by :pymod:`networkx`, this module provides a typed wrapper that
stores :class:`~a2d.ir.nodes.IRNode` instances as node data and connection
anchor metadata on edges.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass

import networkx as nx

from a2d.ir.nodes import CommentNode, IRNode, WidgetNode

logger = logging.getLogger("a2d.ir.graph")


@dataclass
class EdgeInfo:
    """Metadata stored on a directed edge (connection)."""

    origin_anchor: str = "Output"
    destination_anchor: str = "Input"
    is_wireless: bool = False


class WorkflowDAG:
    """A directed acyclic graph representing an IR workflow.

    Each node is keyed by its integer ``node_id`` and stores an
    :class:`IRNode` under the ``"ir"`` attribute.  Edges carry
    :class:`EdgeInfo` under the ``"info"`` attribute.
    """

    def __init__(self) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()

    # ── Mutation ────────────────────────────────────────────────────────

    def add_node(self, ir_node: IRNode) -> None:
        """Add an IR node to the graph."""
        self._graph.add_node(ir_node.node_id, ir=ir_node)

    def add_edge(
        self,
        source_id: int,
        target_id: int,
        origin_anchor: str = "Output",
        destination_anchor: str = "Input",
        is_wireless: bool = False,
    ) -> None:
        """Add a directed edge between two nodes.

        Raises :class:`KeyError` if either node has not been added.
        """
        if source_id not in self._graph:
            raise KeyError(f"Source node {source_id} not in graph")
        if target_id not in self._graph:
            raise KeyError(f"Target node {target_id} not in graph")

        info = EdgeInfo(
            origin_anchor=origin_anchor,
            destination_anchor=destination_anchor,
            is_wireless=is_wireless,
        )
        self._graph.add_edge(source_id, target_id, info=info)

    # ── Queries ─────────────────────────────────────────────────────────

    def get_node(self, node_id: int) -> IRNode:
        """Retrieve the IR node by ID.

        Raises :class:`KeyError` if not found.
        """
        if node_id not in self._graph:
            raise KeyError(f"Node {node_id} not in graph")
        return self._graph.nodes[node_id]["ir"]

    def get_predecessors(self, node_id: int) -> list[IRNode]:
        """Return IR nodes that feed into *node_id*."""
        return [self._graph.nodes[pid]["ir"] for pid in self._graph.predecessors(node_id)]

    def get_successors(self, node_id: int) -> list[IRNode]:
        """Return IR nodes that *node_id* feeds into."""
        return [self._graph.nodes[sid]["ir"] for sid in self._graph.successors(node_id)]

    def get_edge_info(self, source_id: int, target_id: int) -> EdgeInfo:
        """Return the :class:`EdgeInfo` for an edge.

        Raises :class:`KeyError` if edge does not exist.
        """
        if not self._graph.has_edge(source_id, target_id):
            raise KeyError(f"No edge from {source_id} to {target_id}")
        return self._graph.edges[source_id, target_id]["info"]

    def get_outgoing_anchors(self, node_id: int) -> set[str]:
        """Return the set of origin anchors actually connected downstream.

        Useful for determining which output branches of a multi-output node
        (Filter True/False, Join Join/Left/Right) are consumed by successors.
        """
        anchors: set[str] = set()
        for _src, _tgt, data in self._graph.out_edges(node_id, data=True):
            info: EdgeInfo = data["info"]
            anchors.add(info.origin_anchor)
        return anchors

    # ── Traversal ───────────────────────────────────────────────────────

    def topological_order(self) -> list[IRNode]:
        """Return nodes in topological order.

        Raises :class:`nx.NetworkXUnfeasible` if the graph contains a cycle.
        """
        return [self._graph.nodes[nid]["ir"] for nid in nx.topological_sort(self._graph)]

    # Alias for backward compatibility
    topological_sort = topological_order

    def get_source_nodes(self) -> list[IRNode]:
        """Return nodes with no incoming edges (sources / entry points)."""
        return [self._graph.nodes[nid]["ir"] for nid in self._graph.nodes if self._graph.in_degree(nid) == 0]

    def get_sink_nodes(self) -> list[IRNode]:
        """Return nodes with no outgoing edges (sinks / terminal points)."""
        return [self._graph.nodes[nid]["ir"] for nid in self._graph.nodes if self._graph.out_degree(nid) == 0]

    def get_connected_components(self) -> list[set[int]]:
        """Return connected components as sets of node IDs.

        Uses the *undirected* view of the graph so that upstream and
        downstream nodes are grouped together.
        """
        undirected = self._graph.to_undirected()
        return [set(comp) for comp in nx.connected_components(undirected)]

    def all_nodes(self) -> Iterator[IRNode]:
        """Iterate over all IR nodes in the graph (arbitrary order)."""
        for nid in self._graph.nodes:
            yield self._graph.nodes[nid]["ir"]

    def all_node_ids(self) -> list[int]:
        """Return a list of all node IDs."""
        return list(self._graph.nodes)

    def all_edges(self) -> list[tuple[int, int, EdgeInfo]]:
        """Return all edges as (source_id, target_id, EdgeInfo) tuples."""
        return [(u, v, data["info"]) for u, v, data in self._graph.edges(data=True)]

    # ── Validation ──────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        """Run structural checks and return a list of warning/error strings.

        Checks performed:
        - Cycle detection
        - Disconnected sub-graphs (more than one connected component)
        - Nodes referenced by edges but missing from the graph
        """
        issues: list[str] = []

        # Cycle detection
        if not nx.is_directed_acyclic_graph(self._graph):
            try:
                cycle = nx.find_cycle(self._graph)
                cycle_str = " -> ".join(str(e[0]) for e in cycle)
                issues.append(f"Cycle detected: {cycle_str}")
            except nx.NetworkXNoCycle:
                pass  # shouldn't happen but guard anyway

        # Disconnected components (exclude isolated annotation / widget-only nodes)
        components = self.get_connected_components()
        data_components = [
            c
            for c in components
            if not all(isinstance(self._graph.nodes[nid]["ir"], CommentNode | WidgetNode) for nid in c)
        ]
        if len(data_components) > 1:
            issues.append(
                f"Graph has {len(data_components)} disconnected data components: "
                + ", ".join(str(sorted(c)) for c in data_components)
            )

        # Edge references to missing nodes (should not happen via add_edge
        # checks, but verify anyway)
        for u, v in self._graph.edges:
            if u not in self._graph.nodes:
                issues.append(f"Edge references missing source node {u}")
            if v not in self._graph.nodes:
                issues.append(f"Edge references missing target node {v}")

        if issues:
            for issue in issues:
                logger.warning(f"Graph validation: {issue}")
        else:
            logger.debug("Graph validation passed")

        return issues

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def node_count(self) -> int:
        """Number of nodes in the graph."""
        return self._graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        """Number of edges in the graph."""
        return self._graph.number_of_edges()

    def __repr__(self) -> str:
        return f"WorkflowDAG(nodes={self.node_count}, edges={self.edge_count})"
