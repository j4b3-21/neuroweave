import { Background, Controls, MarkerType, Position, ReactFlow, type Edge, type Node } from "@xyflow/react";
import { useMemo } from "react";

import type { Lineage } from "../../api/types";
import { statusColor } from "../../components/common";
import { layeredLayout } from "../../lib/graph";
import { useUi } from "../../state/ui";

const RELATION_LABEL: Record<string, string | undefined> = {
  reusedResultOf: "reused result of",
  sameContentAs: "same content (inferred)",
};

export function LineageGraph({ lineage }: { lineage: Lineage }) {
  const { openArtifact, openRun } = useUi();
  const { nodes, edges } = useMemo(() => {
    const positions = layeredLayout(lineage.nodes.map((n) => n.id), lineage.edges, 230, 70);
    const nodes: Node[] = lineage.nodes.map((n) => {
      const isArtifact = n.type === "artifact";
      const status = n.data.status as string | undefined;
      const cacheHit = Boolean(n.data.cache_hit);
      const root = n.id === lineage.root;
      return {
        id: n.id,
        position: positions.get(n.id) ?? { x: 0, y: 0 },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        connectable: false,
        draggable: false,
        data: {
          label: (
            <div className="text-left">
              <div className="truncate text-[12px] font-medium" title={n.label}>{n.label}</div>
              <div className="truncate text-[11px] text-ink-faint">
                {isArtifact
                  ? `${String(n.data.kind)}${n.data.role === "input" ? ", input file" : ""}`
                  : `${cacheHit ? "reused" : String(status ?? "").toLowerCase()}, ${String(n.data.run_id)}`}
              </div>
            </div>
          ),
        },
        style: {
          width: 190,
          padding: "6px 10px",
          borderRadius: isArtifact ? 14 : 4,
          border: `1px solid ${root ? "var(--color-signal)" : "var(--color-rule)"}`,
          boxShadow: isArtifact ? (root ? "0 0 0 3px rgb(29 106 133 / 0.18)" : "none")
            : `inset 4px 0 0 ${statusColor(status, cacheHit)}`,
          background: isArtifact ? "var(--color-signal-soft)" : "#fff",
          cursor: "pointer",
        },
      };
    });
    const edges: Edge[] = lineage.edges.map((e) => ({
      id: `${e.source}-${e.relation}-${e.target}`,
      source: e.source,
      target: e.target,
      label: RELATION_LABEL[e.relation],
      labelStyle: { fontSize: 11, fill: "#4a5868" },
      className: e.basis === "inferred" ? "nw-inferred" : undefined,
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: "#9aa7b3" },
    }));
    return { nodes, edges };
  }, [lineage]);

  const byId = useMemo(() => new Map(lineage.nodes.map((n) => [n.id, n])), [lineage]);

  return (
    <div className="h-[360px] rounded-md border border-rule bg-canvas">
      <ReactFlow nodes={nodes} edges={edges} fitView fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
                 nodesConnectable={false} nodesDraggable={false} elementsSelectable={false}
                 proOptions={{ hideAttribution: true }} minZoom={0.2}
                 onNodeClick={(_, node) => {
                   const item = byId.get(node.id);
                   if (!item) return;
                   if (item.type === "artifact") openArtifact(item.id);
                   else openRun(String(item.data.run_id));
                 }}>
        <Background gap={20} size={1} color="#d5dce2" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
