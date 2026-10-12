import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { memo } from "react";

import type { NodeDefinition, NodeExecutionRecord, NodeInstance, PortSpec } from "../../api/types";
import { statusColor } from "../../components/common";
import { formatDuration, formatValue } from "../../lib/format";
import { typeFamily, typeLabel } from "../../lib/graph";

export interface NodeCardData extends Record<string, unknown> {
  instance: NodeInstance;
  definition: NodeDefinition | undefined;
  connectedInputs: Set<string>;
  execution: NodeExecutionRecord | undefined;
  errorCount: number;
  stale: boolean;
}

export type NodeCardNode = Node<NodeCardData, "nwNode">;

const FAMILY_COLORS: Record<string, string> = {
  number: "#2f6fb0",
  str: "#7a6a2c",
  bool: "#8b4f9e",
  file: "#4b7f3a",
  table: "#1d6a85",
  figure: "#b4572c",
  markdown: "#5c6470",
  list: "#3f7f88",
  dict: "#6a5ea8",
  any: "#9aa7b3",
};

export const portColor = (port: PortSpec) => FAMILY_COLORS[typeFamily(port.type)] ?? "#57708a";

function PortRow({ port, side, connected, value }: {
  port: PortSpec;
  side: "in" | "out";
  connected: boolean;
  value?: unknown;
}) {
  const missing = side === "in" && port.required && !connected && value === undefined;
  return (
    <div className={`relative flex items-center gap-1.5 py-[3px] text-[12px] ${
      side === "out" ? "justify-end pr-3 pl-6" : "pl-3 pr-6"}`}>
      <Handle id={port.name} type={side === "in" ? "target" : "source"}
              position={side === "in" ? Position.Left : Position.Right}
              aria-label={`${side === "in" ? "Input" : "Output"} port ${port.name}`}
              style={{ background: portColor(port) }} />
      <span className={missing ? "text-fail" : "text-ink"} title={typeLabel(port.type)}>
        {port.name}
      </span>
      {side === "in" && !connected && value !== undefined && (
        <span className="truncate font-mono text-[11px] text-ink-faint" style={{ maxWidth: 110 }}>
          = {formatValue(value)}
        </span>
      )}
      {side === "out" && <span className="text-[11px] text-ink-faint">{typeLabel(port.type)}</span>}
    </div>
  );
}

function NodeCardImpl({ data, selected }: NodeProps<NodeCardNode>) {
  const { instance, definition, connectedInputs, execution, errorCount, stale } = data;
  const rail = execution ? statusColor(execution.status, execution.cache_hit) : "var(--color-rule)";
  return (
    <div data-tour={`node-${instance.id}`}
         className={`min-w-[210px] max-w-[280px] rounded-md border bg-panel ${
      selected ? "border-signal ring-2 ring-signal/25" : errorCount ? "border-fail/60" : "border-rule"}`}
         style={{ boxShadow: `inset 4px 0 0 ${rail}`, opacity: stale ? 0.92 : 1 }}>
      <div className="border-b border-rule-soft py-1.5 pr-3 pl-3.5">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-[13px] font-semibold">
            {instance.label || definition?.label || instance.id}
          </span>
          {errorCount > 0 && (
            <span className="shrink-0 rounded bg-fail/10 px-1 text-[11px] font-medium text-fail"
                  title={`${errorCount} validation error(s)`}>
              {errorCount}
            </span>
          )}
        </div>
        <div className="flex items-center justify-between gap-2 text-[11px] text-ink-faint">
          <span className="truncate font-mono">{instance.id}</span>
          {execution && (
            <span title={execution.cache_note ?? undefined}>
              {execution.cache_hit ? "reused" : execution.status.toLowerCase()}
              {execution.duration_ms !== null && !execution.cache_hit
                ? `, ${formatDuration(execution.duration_ms)}` : ""}
            </span>
          )}
        </div>
      </div>
      {definition ? (
        <div className="py-1">
          {definition.inputs.map((port) => (
            <PortRow key={port.name} port={port} side="in"
                     connected={connectedInputs.has(port.name)} value={instance.params[port.name]} />
          ))}
          {definition.outputs.map((port) => (
            <PortRow key={port.name} port={port} side="out" connected />
          ))}
        </div>
      ) : (
        <p className="px-3 py-2 text-[12px] text-fail">Unknown node type<br />
          <span className="font-mono text-[11px]">{instance.type}</span></p>
      )}
    </div>
  );
}

export const NodeCard = memo(NodeCardImpl);
