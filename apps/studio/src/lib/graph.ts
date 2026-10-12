// Pure helpers between the kernel's Workflow model and the editor. The Workflow (persisted by
// the server) is authoritative; React Flow nodes/edges are always derived from it.

import type { Edge, NodeDefinition, NodeInstance, TypeSpec, Workflow } from "../api/types";

export const edgeKey = (e: Edge) => `${e.source}.${e.source_port}->${e.target}.${e.target_port}`;

export function parseEdgeKey(key: string): Edge | null {
  const match = /^(.+)\.([^.]+)->(.+)\.([^.]+)$/.exec(key);
  if (!match) return null;
  const [, source, source_port, target, target_port] = match as unknown as string[];
  return { source: source!, source_port: source_port!, target: target!, target_port: target_port! };
}

export function typeLabel(spec: TypeSpec): string {
  switch (spec.kind) {
    case "optional":
      return `${typeLabel(spec.args[0]!)} | None`;
    case "union":
      return spec.args.map(typeLabel).join(" | ");
    case "literal":
      return spec.values.map((v) => JSON.stringify(v)).join(" | ");
    case "list":
    case "dict":
      return spec.args.length ? `${spec.name}[${spec.args.map(typeLabel).join(", ")}]` : spec.name;
    default:
      return spec.name;
  }
}

/** Colour family used for port markers, so equal types are visibly alike across nodes. */
export function typeFamily(spec: TypeSpec): string {
  const base = spec.kind === "optional" ? spec.args[0]! : spec;
  if (base.kind === "primitive") return ["int", "float"].includes(base.name) ? "number" : base.name;
  if (base.kind === "literal") return "str";
  if (base.kind === "domain") return base.name.toLowerCase();
  return base.kind;
}

export function uniqueNodeId(workflow: Workflow, base: string): string {
  const taken = new Set(workflow.nodes.map((n) => n.id));
  const clean = base.replace(/[^A-Za-z0-9_-]/g, "_").replace(/^([^A-Za-z_])/, "_$1").slice(0, 60)
    || "node";
  let candidate = clean;
  for (let i = 2; taken.has(candidate); i += 1) candidate = `${clean}_${i}`;
  return candidate;
}

export function addNode(workflow: Workflow, definition: NodeDefinition, x: number, y: number)
  : { workflow: Workflow; nodeId: string } {
  const nodeId = uniqueNodeId(workflow, definition.name);
  const node: NodeInstance = {
    id: nodeId, type: definition.id, label: null, params: {}, position: { x, y },
  };
  return { workflow: { ...workflow, nodes: [...workflow.nodes, node] }, nodeId };
}

export function removeNodes(workflow: Workflow, ids: Set<string>): Workflow {
  return {
    ...workflow,
    nodes: workflow.nodes.filter((n) => !ids.has(n.id)),
    edges: workflow.edges.filter((e) => !ids.has(e.source) && !ids.has(e.target)),
  };
}

export function removeEdges(workflow: Workflow, keys: Set<string>): Workflow {
  return { ...workflow, edges: workflow.edges.filter((e) => !keys.has(edgeKey(e))) };
}

export type ConnectResult = { workflow: Workflow } | { error: string };

/** Structural checks only; type compatibility is decided by the server-side kernel. */
export function connect(workflow: Workflow, edge: Edge): ConnectResult {
  if (edge.source === edge.target) return { error: "A node cannot be connected to itself." };
  if (workflow.edges.some((e) => e.target === edge.target && e.target_port === edge.target_port)) {
    return { error: `Input '${edge.target_port}' of '${edge.target}' is already connected.` };
  }
  const target = workflow.nodes.find((n) => n.id === edge.target);
  if (!target) return { error: `Unknown node '${edge.target}'.` };
  const params = { ...target.params };
  delete params[edge.target_port];
  return {
    workflow: {
      ...workflow,
      nodes: workflow.nodes.map((n) => (n.id === target.id ? { ...n, params } : n)),
      edges: [...workflow.edges, edge],
    },
  };
}

export function updateNode(workflow: Workflow, id: string, patch: Partial<NodeInstance>)
  : Workflow {
  return { ...workflow, nodes: workflow.nodes.map((n) => (n.id === id ? { ...n, ...patch } : n)) };
}

export function setParam(workflow: Workflow, id: string, name: string, value: unknown)
  : Workflow {
  return {
    ...workflow,
    nodes: workflow.nodes.map((n) => {
      if (n.id !== id) return n;
      const params = { ...n.params };
      if (value === undefined) delete params[name];
      else params[name] = value;
      return { ...n, params };
    }),
  };
}

export function moveNodes(workflow: Workflow, moves: Map<string, { x: number; y: number }>)
  : Workflow {
  return {
    ...workflow,
    nodes: workflow.nodes.map((n) => {
      const p = moves.get(n.id);
      return p ? { ...n, position: { x: Math.round(p.x), y: Math.round(p.y) } } : n;
    }),
  };
}

/** Layered left-to-right layout by longest-path depth (used for lineage graphs). */
export function layeredLayout(
  ids: string[], links: { source: string; target: string }[], dx = 260, dy = 96,
): Map<string, { x: number; y: number }> {
  const parents = new Map<string, string[]>(ids.map((id) => [id, []]));
  for (const l of links) parents.get(l.target)?.push(l.source);
  const depth = new Map<string, number>();
  const visiting = new Set<string>();
  const visit = (id: string): number => {
    const known = depth.get(id);
    if (known !== undefined) return known;
    if (visiting.has(id)) return 0;
    visiting.add(id);
    const d = Math.max(-1, ...(parents.get(id) ?? []).map(visit)) + 1;
    visiting.delete(id);
    depth.set(id, d);
    return d;
  };
  ids.forEach(visit);
  const rows = new Map<number, number>();
  const result = new Map<string, { x: number; y: number }>();
  for (const id of ids) {
    const d = depth.get(id) ?? 0;
    const row = rows.get(d) ?? 0;
    rows.set(d, row + 1);
    result.set(id, { x: d * dx, y: row * dy });
  }
  return result;
}
