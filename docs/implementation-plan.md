# NeuroWeave — Implementation Plan

Milestones are ordered by dependency. A task is checked only when its acceptance
criteria are met and its tests pass. Live status is tracked in
`docs/implementation-progress.md`.

## M0 — Audit and planning
- [x] Audit (`docs/architecture-audit.md`), plan (this file), decisions (`docs/decisions.md`)
- [x] Baseline tests recorded (3/3 unittest pass)

## M1 — Core graph and SDK  (depends on M0) — **done**
Deliverables: `neuroweave` package; `@node` decorator; scoped `NodeRegistry`; type
system (`TypeSpec` parsing from annotations, compatibility rules, UI widget hints);
`Workflow`/`NodeInstance`/`Edge` models; validation (unknown node types, unknown ports,
type compatibility, duplicate inputs, missing required inputs, cycles, invalid params);
deterministic topological plan; canonical JSON serialization; snapshot hashing.
Acceptance: workflows round-trip byte-identically; invalid graphs return structured,
actionable errors; plan order is stable across runs.
Tests: `test_sdk.py`, `test_types.py`, `test_graph.py`.

## M2 — Local execution runtime  (depends on M1) — **done**
Deliverables: executor with state machine (PENDING→RUNNING→SUCCEEDED|FAILED|SKIPPED|CANCELLED);
input resolution from upstream outputs, params and defaults; runtime type checks;
per-node log capture; timings; failure propagation (downstream SKIPPED, run FAILED);
cooperative cancellation; deterministic per-node seeds; `log_metric` context API.
Acceptance: failed dependency never yields downstream success; logs and errors persisted.
Tests: `test_runtime.py`.

## M3 — Artifacts and provenance  (depends on M2) — **done**
Deliverables: content-addressed blob store with atomic writes and verification;
serializers (json, table, text, bytes, pickle-with-hash-check); external file inputs hashed
and recorded; SQLite schema for runs, node executions, artifacts, inputs, metrics;
upstream/downstream lineage queries labelled observed vs inferred.
Acceptance: every output has an artifact record with hash; tampering is detected;
lineage of the final report reaches the input CSV.
Tests: `test_artifacts.py`, `test_provenance_experiments.py`.

## M4 — Persistence and reconstruction  (depends on M3) — **done**
Deliverables: workspace API (open/init, workflow CRUD with atomic writes), immutable
content-addressed snapshots per run, historical run inspection, legacy `graph.json` import.
Acceptance: a new process reopens the workspace and reconstructs workflow, runs, artifacts.
Tests: `test_workspace.py`, restart test in `test_end_to_end.py`.

## M5 — Experiments and reproducibility  (depends on M4) — **done**
Deliverables: environment record (Python, platform, packages, Git commit/dirty);
run comparison (snapshot diff, params, inputs, code hashes, statuses, metrics, outputs,
environment); cache with explicit hit records and `--no-cache`; `reproduce` check with
explicit policy (exact content hash).
Acceptance: changing one parameter reruns only the affected subgraph; comparison lists the
parameter change; reproduce on the deterministic example reports all outputs identical.
Tests: `test_cache.py`, `test_provenance_experiments.py`.

## M6 — CLI  (depends on M5) — **done**
Commands: `init`, `nodes`, `workflows`, `validate`, `run`, `runs`, `show`, `artifacts`,
`verify`, `lineage`, `compare`, `reproduce`, `studio`.
Acceptance: each command works against the example; errors exit non-zero with a message.
Tests: `test_cli.py`.

## M7 — API and Studio  (depends on M6) — **done**
Deliverables: FastAPI app (project, catalog, workflows CRUD/validate, runs start/cancel/
status/logs, artifacts content/verify/lineage, compare); catalog and runs computed in child
processes; localhost protections. Studio: shell (sidebar, workspace, inspector, bottom
panel); React Flow editor persisting edits; parameter forms generated from type metadata;
run controls and live state; artifact browser; run history and comparison; lineage view.
Acceptance: all screens show real project data; edits survive reload; a run started in the
Studio produces the same records as the CLI.
Tests: `test_api.py`; Vitest unit tests for graph mapping; manual browser verification.

## M8 — End-to-end demonstration  (depends on M7) — **done**
Deliverables: `examples/research_demo` (CSV → validate → transform → statistics →
SVG chart → Markdown report); integration test covering the 15 acceptance checks.

## M9 — Release readiness — **done**
README, install/dev setup, capabilities and limitations, security notes, GitHub Actions CI
(ruff, pytest on 3.11/3.14, Studio typecheck/test/build).

## Deferred (with prerequisites)
| Feature | Prerequisite |
|---|---|
| Parallel execution | Proven state machine (M2) + thread/process-safe log capture |
| Docker sandbox | Worker protocol (M7) already isolates the run in a process; add container launcher with read-only project mount, no network, resource limits |
| Research Git branching | Snapshots + run history (M4/M5) |
| AI workflow drafting | Validation API (M1/M7) and explicit approval UI |
| Multi-language nodes | Worker protocol generalised beyond Python |
| Collaboration / cloud | Auth model, multi-user storage backend |
