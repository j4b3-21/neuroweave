// TypeScript mirror of the NeuroWeave HTTP API (src/neuroweave/server/app.py).
// The Python kernel owns these contracts; keep this file in step with the Pydantic models.

export type TypeKind =
  | "any" | "none" | "primitive" | "list" | "dict" | "optional" | "union" | "literal" | "file"
  | "domain";

export interface TypeSpec {
  kind: TypeKind;
  name: string;
  args: TypeSpec[];
  values: unknown[];
  bases: string[];
}

export type Widget = "integer" | "number" | "text" | "checkbox" | "select" | "file" | "json";

export interface PortSpec {
  name: string;
  type: TypeSpec;
  description: string | null;
  required: boolean;
  has_default: boolean;
  default: unknown;
  default_repr: string | null;
  editable: boolean;
  widget: Widget | null;
  choices: unknown[] | null;
}

export interface NodeDefinition {
  id: string;
  name: string;
  label: string;
  module: string;
  qualname: string;
  version: string;
  code_hash: string | null;
  description: string | null;
  category: string | null;
  tags: string[];
  inputs: PortSpec[];
  outputs: PortSpec[];
  cache: boolean;
}

export interface ModuleLoadError {
  module: string;
  error: string;
  traceback: string;
}

export interface Catalog {
  definitions: NodeDefinition[];
  errors: ModuleLoadError[];
  loaded_at: string | null;
}

export interface Position {
  x: number;
  y: number;
}

export interface NodeInstance {
  id: string;
  type: string;
  label: string | null;
  params: Record<string, unknown>;
  position: Position;
}

export interface Edge {
  source: string;
  source_port: string;
  target: string;
  target_port: string;
}

export interface Workflow {
  schema_version: number;
  id: string;
  name: string;
  description: string;
  nodes: NodeInstance[];
  edges: Edge[];
}

export interface Issue {
  severity: "error" | "warning";
  code: string;
  message: string;
  node_id: string | null;
  port: string | null;
  edge: Edge | null;
}

export interface ValidationReport {
  valid: boolean;
  issues: Issue[];
  order: string[];
}

export type RunStatus = "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
export type NodeStatus = RunStatus | "SKIPPED";

export interface EnvironmentLock {
  format: string;
  hash: string;
  local: string[];
  neuroweave: { version?: string; source?: string; local?: string };
}

export interface Environment {
  captured_at?: string;
  neuroweave?: string;
  python?: { version: string; implementation: string; executable: string };
  platform?: { system: string; release: string; machine: string };
  git?: { commit: string; branch: string | null; dirty: boolean } | null;
  packages?: Record<string, string>;
  lock?: EnvironmentLock;
  project_lockfiles?: { path: string; hash: string }[];
}

export interface RunRecord {
  id: string;
  workflow_id: string;
  workflow_name: string;
  snapshot_hash: string;
  status: RunStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  seed: number;
  use_cache: boolean;
  trigger: string;
  reproduces_run_id: string | null;
  error: string | null;
  environment: Environment | null;
  worker_pid: number | null;
  cancel_requested: boolean;
}

export interface NodeExecutionRecord {
  id: string;
  run_id: string;
  node_id: string;
  ordinal: number;
  definition_id: string;
  definition_version: string | null;
  code_hash: string | null;
  status: NodeStatus;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  params: Record<string, unknown>;
  seed: number | null;
  cache_key: string | null;
  cache_hit: boolean;
  cache_source_id: string | null;
  cache_note: string | null;
  error: string | null;
  error_type: string | null;
  traceback: string | null;
  log_path: string | null;
}

export interface ArtifactRecord {
  id: string;
  content_hash: string;
  size: number;
  kind: string;
  media_type: string;
  serializer: string | null;
  python_type: string | null;
  role: "output" | "input";
  created_at: string;
  run_id: string | null;
  node_execution_id: string | null;
  node_id: string | null;
  port: string | null;
  source_uri: string | null;
  stored: boolean;
  reused_from: string | null;
}

export interface MetricRecord {
  id: number | null;
  run_id: string;
  node_execution_id: string;
  node_id: string;
  name: string;
  value: number;
  step: number | null;
  direction: string | null;
  created_at: string;
}

export interface NodeExecutionDetail {
  execution: NodeExecutionRecord;
  inputs: Record<string, ArtifactRecord>;
  outputs: ArtifactRecord[];
}

export interface RunDetail {
  run: RunRecord;
  workflow: Workflow;
  nodes: NodeExecutionDetail[];
  metrics: MetricRecord[];
}

export interface ProjectInfo {
  name: string;
  root: string;
  node_modules: string[];
  default_seed: number;
  version: string;
  workflow_count: number;
  run_count: number;
}

export interface WorkflowSummary {
  id: string;
  name: string;
  description: string;
  node_count: number;
  edge_count: number;
  last_run: RunRecord | null;
}

export interface SavedWorkflow {
  workflow: Workflow;
  validation: ValidationReport;
  revision: string;
}

/** A workflow plus the content hash of the stored version it was read from. */
export interface LoadedWorkflow {
  workflow: Workflow;
  revision: string | null;
}

export interface ArtifactDetail {
  artifact: ArtifactRecord;
  previewable: boolean;
  producer: NodeExecutionRecord | null;
  consumers: NodeExecutionRecord[];
}

export interface VerifyResult {
  artifact_id: string;
  content_hash: string;
  stored: boolean;
  ok: boolean;
  message: string;
}

export interface LineageNode {
  id: string;
  type: "artifact" | "execution";
  label: string;
  data: Record<string, unknown>;
}

export interface LineageEdge {
  source: string;
  target: string;
  relation: "used" | "wasGeneratedBy" | "reusedResultOf" | "sameContentAs";
  basis: "observed" | "inferred";
}

export interface Lineage {
  root: string;
  direction: "upstream" | "downstream";
  nodes: LineageNode[];
  edges: LineageEdge[];
  truncated: boolean;
}

export interface WorkflowDiff {
  identical: boolean;
  nodes_added: string[];
  nodes_removed: string[];
  nodes_changed: {
    node_id: string;
    type_change: [string, string] | null;
    label_change: [string | null, string | null] | null;
    param_changes: Record<string, [unknown, unknown]>;
  }[];
  edges_added: string[];
  edges_removed: string[];
  metadata_changes: Record<string, [unknown, unknown]>;
}

export interface NodeComparison {
  node_id: string;
  in_a: boolean;
  in_b: boolean;
  status: [string | null, string | null];
  definition: [string | null, string | null];
  version: [string | null, string | null];
  code_changed: boolean;
  param_changes: Record<string, [unknown, unknown]>;
  input_changes: Record<string, [string | null, string | null]>;
  outputs: Record<string, { a: string | null; b: string | null; identical: boolean }>;
  cache_hit: [boolean | null, boolean | null];
  duration_ms: [number | null, number | null];
}

export interface MetricComparison {
  node_id: string;
  name: string;
  a: number | null;
  b: number | null;
  delta: number | null;
  direction: string | null;
}

export interface RunComparison {
  run_a: RunRecord;
  run_b: RunRecord;
  same_snapshot: boolean;
  workflow_diff: WorkflowDiff;
  seed: [number, number];
  nodes: NodeComparison[];
  metrics: MetricComparison[];
  environment: Record<string, unknown>;
  summary: string[];
}

export interface ReproductionReport {
  original_run_id: string;
  reproduction_run_id: string;
  policy: string;
  verdict: "reproduced" | "not_reproduced" | "failed" | "pending";
  outputs: { node_id: string; port: string; original: string | null; reproduced: string | null;
             identical: boolean }[];
  code_changed_nodes: string[];
  environment_differences: Record<string, unknown>;
  environment_match: "identical" | "different" | "unknown";
  isolated: boolean;
  notes: string[];
}
