import type {
  ArtifactDetail, ArtifactRecord, Catalog, Lineage, LoadedWorkflow, ProjectInfo, ReproductionReport,
  RunComparison, RunDetail, RunRecord, SavedWorkflow, ValidationReport, VerifyResult, Workflow,
  WorkflowSummary,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail: unknown) {
    super(message);
  }
}

function describe(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    return String((detail as { message: unknown }).message);
  }
  if (Array.isArray(detail)) {
    return detail.map((d) => (d && typeof d === "object" && "msg" in d ? String(d.msg) : String(d)))
      .join("; ");
  }
  return "Request failed.";
}

async function send(method: string, path: string, body?: unknown,
                    extraHeaders: Record<string, string> = {}): Promise<Response> {
  const headers: Record<string, string> = { ...extraHeaders };
  if (method !== "GET") headers["X-NeuroWeave-Client"] = "studio";
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let response: Response;
  try {
    response = await fetch(path, {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Cannot reach the NeuroWeave server. Is `nw studio` running?", null);
  }
  if (!response.ok) {
    const isJson = response.headers.get("content-type")?.includes("application/json");
    const payload: unknown = isJson ? await response.json() : await response.text();
    const detail = isJson ? (payload as { detail?: unknown }).detail : payload;
    throw new ApiError(response.status, describe(detail), detail);
  }
  return response;
}

async function request<T>(method: string, path: string, body?: unknown,
                          headers?: Record<string, string>): Promise<T> {
  const response = await send(method, path, body, headers);
  if (response.status === 204) return undefined as T;
  const isJson = response.headers.get("content-type")?.includes("application/json");
  return (isJson ? await response.json() : await response.text()) as T;
}

const q = (params: Record<string, string | number | undefined | null>) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
};

const enc = encodeURIComponent;

export const api = {
  project: () => request<ProjectInfo>("GET", "/api/project"),
  updateProject: (update: Partial<Pick<ProjectInfo, "name" | "node_modules" | "default_seed">>) =>
    request<ProjectInfo>("PUT", "/api/project", update),
  catalog: (refresh = false) => request<Catalog>("GET", `/api/nodes${q({ refresh: refresh ? "true" : undefined })}`),

  workflows: () => request<WorkflowSummary[]>("GET", "/api/workflows"),
  workflow: async (id: string): Promise<LoadedWorkflow> => {
    const response = await send("GET", `/api/workflows/${enc(id)}`);
    const etag = response.headers.get("etag");
    return { workflow: await response.json() as Workflow, revision: etag ? etag.replace(/"/g, "") : null };
  },
  createWorkflow: (body: { id: string; name: string; description?: string }) =>
    request<Workflow>("POST", "/api/workflows", body),
  /** With `revision`, the server refuses (409) if the stored workflow changed since it was read. */
  saveWorkflow: (workflow: Workflow, revision?: string | null) =>
    request<SavedWorkflow>("PUT", `/api/workflows/${enc(workflow.id)}`, workflow,
      revision ? { "If-Match": `"${revision}"` } : {}),
  deleteWorkflow: (id: string) => request<void>("DELETE", `/api/workflows/${enc(id)}`),
  validate: (workflow: Workflow) =>
    request<ValidationReport>("POST", `/api/workflows/${enc(workflow.id)}/validate`, workflow),
  startRun: (workflowId: string, body: { seed?: number | null; use_cache: boolean }) =>
    request<RunRecord>("POST", `/api/workflows/${enc(workflowId)}/runs`, body),

  runs: (workflowId?: string) => request<RunRecord[]>("GET", `/api/runs${q({ workflow_id: workflowId })}`),
  run: (id: string) => request<RunDetail>("GET", `/api/runs/${enc(id)}`),
  logs: (runId: string, nodeId: string) =>
    request<string>("GET", `/api/runs/${enc(runId)}/logs/${enc(nodeId)}`),
  cancelRun: (id: string) => request<RunRecord>("POST", `/api/runs/${enc(id)}/cancel`),
  reproduce: (id: string, body: { isolated?: boolean; rebuild?: boolean; allow_build?: boolean } = {}) =>
    request<RunRecord>("POST", `/api/runs/${enc(id)}/reproduce`, body),
  reproduction: (id: string) => request<ReproductionReport>("GET", `/api/runs/${enc(id)}/reproduction`),
  compare: (a: string, b: string) => request<RunComparison>("GET", `/api/compare${q({ a, b })}`),

  artifacts: (filters: { run_id?: string; kind?: string; role?: string } = {}) =>
    request<ArtifactRecord[]>("GET", `/api/artifacts${q(filters)}`),
  artifact: (id: string) => request<ArtifactDetail>("GET", `/api/artifacts/${enc(id)}`),
  artifactText: async (id: string): Promise<string> => {
    const response = await fetch(`/api/artifacts/${enc(id)}/content`);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new ApiError(response.status, describe(body.detail), body.detail);
    }
    return response.text();
  },
  artifactUrl: (id: string, download = false) =>
    `/api/artifacts/${enc(id)}/content${download ? "?download=true" : ""}`,
  verify: (id: string) => request<VerifyResult>("POST", `/api/artifacts/${enc(id)}/verify`),
  lineage: (id: string, direction: "upstream" | "downstream") =>
    request<Lineage>("GET", `/api/artifacts/${enc(id)}/lineage${q({ direction })}`),
};

export const isActive = (status: string | undefined) => status === "PENDING" || status === "RUNNING";
