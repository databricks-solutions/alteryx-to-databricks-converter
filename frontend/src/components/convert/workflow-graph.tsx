import { useCallback, useMemo, useState } from "react";
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
import type { DagData, DagNode } from "@/lib/api";
import "@xyflow/react/dist/style.css";

interface WorkflowGraphProps {
  dagData: DagData;
  onNodeSelect?: (nodeId: number) => void;
}

function getBorderColor(confidence: number): string {
  if (confidence >= 0.9) return "#22c55e";
  if (confidence >= 0.6) return "#eab308";
  return "#ef4444";
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max) + "..." : s;
}

// Node dimensions used by both rendering AND dagre layout — keep in sync.
// Width is wide enough to fit the longest tool names ("DynamicRename",
// "TextToColumns", "PrincipalComponents", etc.) without truncation.
const NODE_WIDTH = 200;
const NODE_HEIGHT = 56;

function useAutoLayout(dagData: DagData) {
  return useMemo(() => {
    // Always run dagre. The original Alteryx canvas positions are tuned for
    // Alteryx's UI (smaller nodes, denser packing) and produce overlapping,
    // illegible layouts when applied here. Dagre's LR layout gives a clean
    // left-to-right dataflow with proper rank/node separation.
    const g = new dagre.graphlib.Graph();
    g.setDefaultEdgeLabel(() => ({}));
    g.setGraph({
      rankdir: "LR",
      nodesep: 36, // vertical gap between siblings in the same rank
      ranksep: 110, // horizontal gap between ranks (room for the edge marker)
      marginx: 20,
      marginy: 20,
    });
    for (const n of dagData.nodes) {
      g.setNode(String(n.node_id), { width: NODE_WIDTH, height: NODE_HEIGHT });
    }
    for (const e of dagData.edges) {
      g.setEdge(String(e.source_id), String(e.target_id));
    }
    dagre.layout(g);

    const nodes: Node[] = dagData.nodes.map((n) => {
      const laid = g.node(String(n.node_id));
      return {
        id: String(n.node_id),
        position: { x: laid.x - NODE_WIDTH / 2, y: laid.y - NODE_HEIGHT / 2 },
        // Explicit handles for left-to-right routing — without these,
        // react-flow defaults to top/bottom (TB) which produces ugly U-turns
        // in an LR graph.
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        data: {
          label: n.annotation
            ? `${n.tool_type}\n${truncate(n.annotation, 26)}`
            : n.tool_type,
          dagNode: n,
        },
        style: {
          border: `2px solid ${getBorderColor(n.conversion_confidence)}`,
          borderRadius: "10px",
          padding: "10px 14px",
          fontSize: "12px",
          fontWeight: 500,
          background: "var(--bg-card)",
          color: "var(--fg)",
          width: NODE_WIDTH,
          minHeight: NODE_HEIGHT,
          whiteSpace: "pre-line" as const,
          cursor: "pointer",
          textAlign: "center" as const,
          // Subtle elevation so nodes pop above the dot grid + edges
          boxShadow: "0 1px 2px rgba(0,0,0,0.18)",
        },
      };
    });

    // Edges: solid (not animated dashed — that read as "almost invisible")
    // with a stronger stroke colour and a small arrowhead so dataflow
    // direction is obvious. `smoothstep` routes around nodes more cleanly
    // than the default bezier on dense layouts.
    const edges: Edge[] = dagData.edges.map((e, i) => ({
      id: `e-${i}`,
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
  }, [dagData]);
}

export function WorkflowGraph({ dagData, onNodeSelect }: WorkflowGraphProps) {
  const { nodes, edges } = useAutoLayout(dagData);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; node: DagNode } | null>(null);

  const onNodeClick = useCallback(
    (_: unknown, node: Node) => {
      const dagNode = node.data?.dagNode as DagNode | undefined;
      if (dagNode && onNodeSelect) onNodeSelect(dagNode.node_id);
    },
    [onNodeSelect],
  );

  const onNodeMouseEnter = useCallback(
    (_: React.MouseEvent, node: Node) => {
      const dagNode = node.data?.dagNode as DagNode | undefined;
      if (dagNode) {
        setTooltip({
          x: (node.position?.x ?? 0) + 190,
          y: (node.position?.y ?? 0),
          node: dagNode,
        });
      }
    },
    [],
  );

  const onNodeMouseLeave = useCallback(() => setTooltip(null), []);

  const showMinimap = nodes.length > 10;

  return (
    <div className="relative h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.2}
        maxZoom={2}
        onNodeClick={onNodeClick}
        onNodeMouseEnter={onNodeMouseEnter}
        onNodeMouseLeave={onNodeMouseLeave}
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
        <span className="font-medium">Confidence:</span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded border-2 border-green-500" /> High
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded border-2 border-yellow-500" /> Medium
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded border-2 border-red-500" /> Low
        </span>
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="absolute z-10 rounded-lg bg-[var(--bg-card)] border border-[var(--border)] shadow-lg px-3 py-2 text-xs pointer-events-none max-w-[220px]"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          <div className="font-medium text-[var(--fg)]">{tooltip.node.tool_type}</div>
          {tooltip.node.annotation && (
            <div className="text-[var(--fg-muted)] mt-0.5">{tooltip.node.annotation}</div>
          )}
          <div className="mt-1 space-y-0.5 text-[var(--fg-muted)]">
            <div>Confidence: {(tooltip.node.conversion_confidence * 100).toFixed(0)}%</div>
            <div>Method: {tooltip.node.conversion_method}</div>
            <div>Node ID: {tooltip.node.node_id}</div>
          </div>
        </div>
      )}
    </div>
  );
}
