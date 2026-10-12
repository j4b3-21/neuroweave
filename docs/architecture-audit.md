# NeuroWeave — Architecture Audit

Audit date: 2026-10-12. Baseline commit: `5555b7f` (first commit of the local tree).

## 0. Sources examined

| Source | Role | Location |
|---|---|---|
| `ResearchOS.md` | Long-term product vision (28 layers) | repo root (copied from the parent research folder, where it previously lived outside the repository) |
| `Architecture.md` | Current architectural proposal | repo root |
| Local source tree | Evidence of actual implementation | `src/`, `tests/`, `pyproject.toml` |
| GitHub `j4b3-21/neuroweave` | Earlier prototype (3 commits) | `Tool/` Panel upload app, neuro-imaging README |

There were no `AGENTS.md`, CI workflows, migrations, examples, lockfiles, or frontend
code. The local directory was not a Git repository.

## 1. Current architecture (baseline)

```
pyproject.toml          name=neuroweave, requires-python>=3.14, deps: typer; script nw = src.cli.main:main
src/cli/workspace.py    initialize_workspace(): creates .neuroweave/{project.json,graph.json,snapshots/,runs/,artifacts/}
src/cli/main.py         Typer app with one command: `nw init`
src/sdk/python/         @Node decorator, NodeRegistry (class-level dict), NodeMetadata dataclasses, introspection helpers
tests/test_phase_one.py 3 unittest tests for `nw init`
```

GitHub remote: an unrelated Panel file-upload widget (`Tool/`) plus a README that frames
NeuroWeave as a neuro-imaging platform (scanner normalisation, DICOM, clinical viewer).

## 2. Implementation status

| Subsystem | Status | Evidence |
|---|---|---|
| `nw init` workspace creation | Implemented and working | 3/3 baseline tests pass (`python -m unittest discover -s tests`) |
| `@Node` decorator / metadata | Present but defective | see §5 |
| Node registry | Present but defective | name collisions overwrite silently |
| Graph kernel (model, validation, planning) | Documented but missing | `graph.json` is written as `{nodes:[], edges:[]}` and never read |
| Execution runtime | Documented but missing | — |
| Docker sandbox | Documented but missing | — |
| Artifact store | Documented but missing | `artifacts/` directory only |
| Experiment engine | Documented but missing | `runs/` directory only |
| Provenance engine | Documented but missing | — |
| Snapshots | Documented but missing | `snapshots/` directory only |
| Studio (visual editor) | Documented but missing | no frontend code |
| PostgreSQL storage | Premature for MVP | a local-first single-user tool does not need a server DB |
| JavaScript SDK, desktop app, workers, packages/* | Premature for MVP | — |
| Panel upload tool (GitHub) | Unnecessary | copies an uploaded `.py` to an arbitrary user-chosen path; unrelated to the graph model |

## 3. Architectural inconsistencies

1. **Package named `src`.** The installable top-level package is literally `src`
   (`import src.sdk.python`). Any other project using the same convention collides on
   import, and the public SDK path is unreadable. → Rename to `neuroweave` using a proper
   src-layout (`src/neuroweave/`).
2. **`@Node` vs `@node`.** Both documents show lowercase `@node`; the code exposes `Node`.
   → Provide `node` as the public name, keep `Node` as an alias.
3. **Repository structure in `Architecture.md`** (apps/, core/, runtime/, sdk/, storage/,
   packages/ with 20+ directories) is far wider than the implementation needs. Most of those
   directories would be empty placeholders. → Use one Python package with focused
   subpackages and one Studio app; document the mapping (see `docs/architecture.md`).
4. **Product scope.** The GitHub README describes a neuro-imaging platform; `Architecture.md`
   and the task brief describe a general graph-native reproducible-research platform.
   → `Architecture.md` is newer and is the agreed direction. Neuro-imaging capabilities
   become a future *domain pack* built on the core.
5. **`graph.json` singleton.** The layout allows exactly one graph per project, while the
   Studio requirements (workflow list, history) need several. → Keep `.neuroweave/` and the
   documented subdirectories, add `workflows/<id>.json`; leave any legacy `graph.json`
   untouched (non-destructive), and import it once as workflow `main` if it contains nodes.
6. **`Architecture.md` claims "Every result should be reproducible"** and "automatically
   records environment". Recording metadata does not guarantee reproduction. → Documentation
   now states explicit reproducibility *checks* and limits.

## 4. Missing core capabilities

Graph model and validation, type compatibility, deterministic planning, execution runtime,
artifact store with hashing, durable run records, provenance queries, snapshots,
run comparison, caching, environment capture, API for the Studio, the Studio itself, an
end-to-end example, and any automated test beyond `nw init`.

## 5. Reliability and security risks (baseline)

- `introspection.py` uses `annotation.__name__`: `list[int]` → `"list"`, `int | None` →
  `"Union"`; type information required for connection validation is lost. Non-type
  annotations (e.g. string literals with unresolved forward refs) raise inside
  `get_type_hints`.
- `NodeRegistry` keys by bare function name: `a.load` and `b.load` silently overwrite each
  other (verified). Registry is process-global class state with no isolation for tests.
- `@Node` used without parentheses silently replaces the function with the inner decorator
  (verified) — a researcher's function disappears without an error.
- `version: bool` flag has no semantics; there is no node version or code identity.
- Description ignores the function docstring.
- `nw init` writes files non-atomically (crash mid-write leaves a truncated JSON).
- Panel prototype writes uploaded bytes to any path the user types (path traversal by design).
- No statement anywhere about trust model: executing a workflow runs arbitrary Python.

## 6. Unnecessary complexity to avoid

- PostgreSQL, Redis, message brokers, Kubernetes, distributed workers for v0.
- Separate `packages/graph-schema`, `shared-types`, `ui-components` packages: the graph
  schema is owned by the Python kernel and exposed through the API (JSON Schema/Pydantic);
  the Studio keeps one TypeScript mirror of the API types.
- Five-level-deep SDK package nesting (`src/sdk/python/decorators/node.py`).

## 7. Recommended changes (adopted — see `docs/decisions.md`)

1. Single Python package `neuroweave` (src layout) with subpackages `sdk`, `kernel`,
   `runtime`, `store`, `server`, plus `cli`.
2. Pydantic v2 models for all persisted/API contracts; stable, distinct identifiers
   (workflow id, snapshot hash, run id, node-execution id, artifact id, content hash).
3. Local persistence: workflow definitions as JSON files (human-readable, Git-diffable);
   content-addressed snapshots and artifact blobs on disk; SQLite (stdlib) as the
   authoritative, transactional store for runs, node executions, artifacts metadata,
   provenance edges and metrics.
4. Execution: deterministic sequential scheduler with explicit state machine; Studio-launched
   runs execute in a child process so user code never runs in the API server and can be
   cancelled; stale RUNNING records are reconciled.
5. Caching keyed on node identity + version + source hash + parameters + input content
   hashes + seed + Python version; explicit cache-hit records; `--no-cache` override.
6. FastAPI server bound to 127.0.0.1 with Host-header and custom-header checks; serves the
   built Studio.
7. Studio: React + TypeScript + Vite + Tailwind + React Flow + TanStack Query.

## 8. Deferred features

Docker sandboxing (documented as *not* implemented; local execution is trusted-code-only),
parallel execution, multi-language runtimes, distributed/cloud workers, marketplace and
package manager, embeddings, AI recommendations/agents, natural-language workflows, paper
generation, collaboration, Research Git branching/merging, multi-user permissions,
PostgreSQL backend, desktop shell, JavaScript SDK, neuro-imaging domain pack.

## 9. Compatibility considerations

- `nw init` semantics preserved: idempotent, preserves existing files, same summary output.
  It no longer creates `graph.json`; it creates `workflows/`. `project.json` gains fields
  but keeps all v1 keys; v1 files are upgraded in place only by adding missing keys.
- `from src.sdk.python import Node, NodeRegistry` is removed (the `src` package is gone).
  No external consumers exist (package never published); the old GitHub `Tool/` app is
  dropped.
- `requires-python` lowered from `>=3.14` to `>=3.11` (nothing needed 3.14); CI tests 3.11
  and 3.14.
