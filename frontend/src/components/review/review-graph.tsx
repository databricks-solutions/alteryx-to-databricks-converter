import { useCallback, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  MarkerType,
  Position,
  type Node,
  type Edge,
} from "@xyflow/react";
import dagre from "dagre";
import type { ReviewNode, ReviewEdge, ReviewStatus, ReviewDecision } from "@/lib/api";
import "@xyflow/react/dist/style.css";

interface ReviewGraphProps {
  nodes: ReviewNode[];
  edges: ReviewEdge[];
  selectedId: number | null;
  onNodeSelect: (nodeId: number) => void;
}

// Node border colour keyed by conversion status. A resolved decision
// (accepted/edited) always reads green regardless of the original status,
// and a reject reads red — so the canvas doubles as a review-progress view.
function statusColor(status: ReviewStatus, decision: ReviewDecision): string {
  if (decision === "accepted" || decision === "edited") return "#22c55e";
  if (decision === "rejected") return "#ef4444";
  switch (status) {
    case "auto_accepted":
      return "#22c55e";
    case "needs_review":
      return "#eab308";
    case "cannot_convert":
      return "#ef4444";
  }
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max) + "..." : s;
}

// Kept in sync with the layout dimensions (mirrors workflow-graph.tsx).
const NODE_WIDTH = 200;
const NODE_HEIGHT = 56;

function useAutoLayout(
  reviewNodes: ReviewNode[],
  reviewEdges: ReviewEdge[],
  selectedId: number | null,
) {
  return useMemo(() => {
    const g = new dagre.graphlib.Graph();
    g.setDefaultEdgeLabel(() => ({}));
    g.setGraph({
      rankdir: "LR",
      nodesep: 36,
      ranksep: 110,
      marginx: 20,
      marginy: 20,
    });
    for (const n of reviewNodes) {
      g.setNode(String(n.node_id), { width: NODE_WIDTH, height: NODE_HEIGHT });
    }
    for (const e of reviewEdges) {
      g.setEdge(String(e.source_id), String(e.target_id));
    }
    dagre.layout(g);

    const nodes: Node[] = reviewNodes.map((n) => {
      const laid = g.node(String(n.node_id));
      const selected = n.node_id === selectedId;
      const color = statusColor(n.status, n.decision);
      return {
        id: String(n.node_id),
        position: { x: laid.x - NODE_WIDTH / 2, y: laid.y - NODE_HEIGHT / 2 },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        data: {
          label: n.annotation
            ? `${n.tool_type}\n${truncate(n.annotation, 26)}`
            : n.tool_type,
        },
        style: {
          border: `2px solid ${color}`,
          borderRadius: "10px",
          padding: "10px 14px",
          fontSize: "12px",
          fontWeight: 500,
          background: selected ? "var(--ring)" : "var(--bg-card)",
          color: selected ? "#fff" : "var(--fg)",
          width: NODE_WIDTH,
          minHeight: NODE_HEIGHT,
          whiteSpace: "pre-line" as const,
          cursor: "pointer",
          textAlign: "center" as const,
          boxShadow: selected
            ? "0 0 0 3px var(--ring)"
            : "0 1px 2px rgba(0,0,0,0.18)",
        },
      };
    });

    const edges: Edge[] = reviewEdges.map((e, i) => ({
      id: `re-${i}`,
      source: String(e.source_id),
      target: String(e.target_id),
      type: "smoothstep",
      animated: false,
      style: { stroke: "var(--fg-muted)", strokeWidth: 1.75 },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        width: 16,
        height: 16,
        color: "var(--fg-muted)",
      },
    }));

    return { nodes, edges };
  }, [reviewNodes, reviewEdges, selectedId]);
}

export function ReviewGraph({ nodes, edges, selectedId, onNodeSelect }: ReviewGraphProps) {
  const { nodes: flowNodes, edges: flowEdges } = useAutoLayout(nodes, edges, selectedId);

  const onNodeClick = useCallback(
    (_: unknown, node: Node) => {
      onNodeSelect(Number(node.id));
    },
    [onNodeSelect],
  );

  const showMinimap = flowNodes.length > 10;

  return (
    <div className="relative h-full w-full">
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.2}
        maxZoom={2}
        onNodeClick={onNodeClick}
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{
          type: "smoothstep",
          style: { stroke: "var(--fg-muted)", strokeWidth: 1.75 },
        }}
      >
        <Background />
        <Controls />
        {showMinimap && (
          <MiniMap
            style={{ background: "var(--bg-sidebar)" }}
            maskColor="rgba(0,0,0,0.2)"
          />
        )}
      </ReactFlow>

      {/* Legend */}
      <div className="absolute bottom-3 left-3 flex items-center gap-3 rounded-lg bg-[var(--bg-card)]/90 backdrop-blur px-3 py-2 text-[11px] text-[var(--fg-muted)] border border-[var(--border)]">
        <span className="font-medium">Status:</span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded border-2 border-green-500" /> Auto / resolved
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded border-2 border-yellow-500" /> Needs review
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded border-2 border-red-500" /> Cannot convert
        </span>
      </div>
    </div>
  );
}
