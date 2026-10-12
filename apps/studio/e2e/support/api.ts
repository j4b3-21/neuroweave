/**
 * Thin client for the real NeuroWeave HTTP API, used by tests to check what the Studio did.
 * Responses are never mocked; every assertion reads the server's persisted state.
 */
import { type APIRequestContext, expect } from "@playwright/test";

export interface RunRecord {
  id: string;
  workflow_id: string;
  snapshot_hash: string;
  status: string;
  seed: number;
  use_cache: boolean;
  trigger: string;
  reproduces_run_id: string | null;
  error: string | null;
  environment: Record<string, unknown> | null;
}

export interface NodeExecution {
  id: string;
  run_id: string;
  node_id: string;
  status: string;
  params: Record<string, unknown>;
  cache_key: string | null;
  cache_hit: boolean;
  cache_source_id: string | null;
  cache_note: string | null;
  error: string | null;
  error_type: string | null;
  traceback: string | null;
}

export interface Artifact {
  id: string;
  content_hash: string;
  size: number;
  role: "input" | "output";
  run_id: string | null;
  node_id: string | null;
  node_execution_id: string | null;
  port: string | null;
  stored: boolean;
  reused_from: string | null;
}

export interface RunDetail {
  run: RunRecord;
  workflow: { id: string; nodes: { id: string; params: Record<string, unknown> }[] };
  nodes: { execution: NodeExecution; inputs: Record<string, Artifact>; outputs: Artifact[] }[];
  metrics: { node_id: string; name: string; value: number }[];
}

export interface Comparison {
  run_a: RunRecord;
  run_b: RunRecord;
  same_snapshot: boolean;
  summary: string[];
  nodes: {
    node_id: string;
    param_changes: Record<string, [unknown, unknown]>;
    outputs: Record<string, { a: string | null; b: string | null; identical: boolean }>;
    cache_hit: [boolean | null, boolean | null];
  }[];
  metrics: { node_id: string; name: string; a: number | null; b: number | null; delta: number | null }[];
}

export interface Reproduction {
  original_run_id: string;
  reproduction_run_id: string;
  policy: string;
  verdict: "reproduced" | "not_reproduced" | "failed" | "pending";
  outputs: { node_id: string; port: string; original: string | null; reproduced: string | null;
             identical: boolean }[];
  notes: string[];
}

export interface Lineage {
  nodes: { id: string; type: "artifact" | "execution"; label: string }[];
  edges: { source: string; target: string; relation: string; basis: string }[];
}

const TERMINAL = new Set(["SUCCEEDED", "FAILED", "CANCELLED"]);

export class Api {
  constructor(private readonly request: APIRequestContext, private readonly baseUrl: () => string) {}

  async get<T>(path: string): Promise<T> {
    const response = await this.request.get(`${this.baseUrl()}${path}`);
    expect(response.ok(), `GET ${path} -> ${response.status()} ${await response.text()}`).toBe(true);
    return response.json() as Promise<T>;
  }

  async post<T>(path: string, data?: unknown): Promise<T> {
    const response = await this.request.post(`${this.baseUrl()}${path}`, {
      data, headers: { "X-NeuroWeave-Client": "e2e" },
    });
    expect(response.ok(), `POST ${path} -> ${response.status()} ${await response.text()}`).toBe(true);
    return response.json() as Promise<T>;
  }

  async workflow(id: string): Promise<{ workflow: { nodes: { id: string; params: Record<string, unknown> }[] };
                                        revision: string }> {
    const response = await this.request.get(`${this.baseUrl()}/api/workflows/${id}`);
    expect(response.ok()).toBe(true);
    return { workflow: await response.json(), revision: (response.headers().etag ?? "").replace(/"/g, "") };
  }

  runs(workflowId?: string): Promise<RunRecord[]> {
    return this.get(`/api/runs${workflowId ? `?workflow_id=${workflowId}` : ""}`);
  }

  run(id: string): Promise<RunDetail> {
    return this.get(`/api/runs/${id}`);
  }

  startRun(workflowId: string, body: { seed?: number; use_cache?: boolean } = {}): Promise<RunRecord> {
    return this.post(`/api/workflows/${workflowId}/runs`, body);
  }

  /** Poll the server until the run reaches a terminal state, then return its full record. */
  async waitForRun(id: string, timeout = 60_000): Promise<RunDetail> {
    await expect.poll(async () => (await this.run(id)).run.status, { timeout, intervals: [200, 500] })
      .toMatch(/^(SUCCEEDED|FAILED|CANCELLED)$/);
    const detail = await this.run(id);
    expect(TERMINAL.has(detail.run.status)).toBe(true);
    return detail;
  }

  compare(a: string, b: string): Promise<Comparison> {
    return this.get(`/api/compare?a=${a}&b=${b}`);
  }

  reproduction(runId: string): Promise<Reproduction> {
    return this.get(`/api/runs/${runId}/reproduction`);
  }

  artifacts(runId: string, role?: "input" | "output"): Promise<Artifact[]> {
    return this.get(`/api/artifacts?run_id=${runId}${role ? `&role=${role}` : ""}`);
  }

  lineage(artifactId: string, direction: "upstream" | "downstream" = "upstream"): Promise<Lineage> {
    return this.get(`/api/artifacts/${artifactId}/lineage?direction=${direction}`);
  }

  logs(runId: string, nodeId: string): Promise<string> {
    return this.request.get(`${this.baseUrl()}/api/runs/${runId}/logs/${nodeId}`).then((r) => r.text());
  }
}

/** Executions of a run keyed by workflow node id. */
export function byNode(detail: RunDetail): Map<string, RunDetail["nodes"][number]> {
  return new Map(detail.nodes.map((n) => [n.execution.node_id, n]));
}
