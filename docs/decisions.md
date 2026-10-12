# Architectural decisions

Each entry records a decision taken while implementing v0.2.0, the alternatives considered
and the consequences. Entries are append-only; a later decision may supersede an earlier one.

## D1. One Python package with focused subpackages

**Context.** The prototype used a top-level package literally named `src` (`src.cli`,
`src.sdk.python...`), and `Architecture.md` proposed many top-level service directories.
**Decision.** A single installable package, `neuroweave`, with `kernel`, `sdk`, `runtime`,
`store` and `server` subpackages, plus one frontend app in `apps/studio`. The old modules were
moved (`git mv`) and rewritten so history is preserved.
**Consequences.** `import neuroweave` works after `pip install`; the proposal's components
map onto subpackages (see [architecture.md](architecture.md#9-mapping-to-the-original-proposal-architecturemd)).
The `nw` entry point is `neuroweave.cli:main`.

## D2. `@node` returns the original function

**Context.** The prototype's `@Node` replaced the function with a metadata wrapper, so
decorated functions could not be called or unit-tested normally.
**Decision.** `@node` (alias `Node`) registers a definition and returns the function
unchanged, with the definition attached as `__neuroweave_node__`. Registration goes to an
explicit registry (`registry=`) or the process-wide `default_registry`.
**Consequences.** Node functions remain plain Python. Tests use isolated registries.

## D3. Workflow files for the present, SQLite for history

**Context.** The prototype stored one `graph.json` per project.
**Decision.** Editable workflows are JSON files (`workflows/<id>.json`); every executed
version is frozen as `snapshots/<sha256>.json`; runs, node executions, artifacts, inputs and
metrics live in SQLite (WAL mode). A legacy `graph.json` is imported once as workflow `main`
and never modified.
**Alternatives.** Everything in SQLite (harder to diff and review), or everything in JSON
files (no transactions, slow queries over history).
**Consequences.** Workflows are reviewable in Git; history queries are transactional;
outputs, metrics and the `SUCCEEDED` state of a node are committed atomically.

## D4. Content-addressed artifact store

**Decision.** Artifact bytes are stored once under their SHA-256 (`objects/<hh>/<hash>`) with
atomic writes; each output gets its own artifact record (id, run, node, port, serializer,
media type) pointing at the hash. Reads used for execution are always hash-verified.
**Consequences.** Identical results are deduplicated; tampering or corruption is detected
(`nw verify`, and before any reuse). Deleting runs does not yet garbage-collect blobs.

## D5. Deterministic serializers, pickle only as a fallback

**Decision.** `Table`, `Figure`, `Markdown`, text, bytes and JSON values have
deterministic encodings (JSON with sorted keys and no whitespace), so equal values produce
equal hashes. Other Python objects are pickled.
**Consequences.** Reproduction checks are meaningful for the built-in types. Pickled
outputs may differ byte-wise between Python versions, and loading a pickle executes code, so
pickles are only loaded after their hash matches the record written by this workspace.

## D6. Runs from the Studio execute in a separate worker process

**Context.** Executing user code inside the API server would let a crash, infinite loop or
`sys.exit` take the server down, and would make cancellation impossible.
**Decision.** `RunManager` spawns `python -m neuroweave.runtime.worker <run_id>`; the server
only reads state from the database. Cancellation is `SIGTERM`, escalated to `SIGKILL` after
10 seconds. Runs whose worker disappeared are reconciled to `FAILED`. The CLI executes
in-process.
**Consequences.** This is process isolation for robustness, **not** a security boundary (see
D12).

## D7. Node catalog discovered in a child process

**Decision.** The server never imports user modules. It runs
`python -m neuroweave.runtime.catalog`, which imports the configured modules and prints the
definitions (and import errors) as JSON. Results are cached until a module file's
modification time changes; the Studio can force a reload.
**Consequences.** Edited node code is picked up without restarting `nw studio`; a module
with import-time side effects cannot affect the server.

## D8. Explicit cache keys and recorded reuse

**Decision.** A node result is reused only when node id, declared version, source hash,
parameters, input content hashes (with their serializer), derived seed and Python
implementation and minor version all match. A cache hit is recorded as its own node
execution with `cache_hit`, `cache_source_id` and a human-readable `cache_note`, and its
outputs as new artifact records with `reused_from`. `cache=False` and `--no-cache` disable
reuse.
**Consequences.** Every run has a complete record even when nothing executed. Known blind
spots are documented in [reproducibility.md](reproducibility.md).

## D9. Reproduction policy: exact content hashes

**Decision.** `reproduce` re-executes the original snapshot with the original seed and the
cache disabled, using the code currently installed, and declares the run reproduced only if
every output the original recorded has an identical SHA-256. Code and environment
differences are reported as notes rather than silently ignored.
**Alternatives.** Tolerance-based numeric comparison (useful but needs per-output
configuration; deferred).
**Consequences.** Floating-point output that differs in the last bit is reported as not
reproduced. This is deliberately strict.

## D10. Deterministic per-node seeds

**Decision.** Each run has a seed (project default `0`); each node receives
`int(sha256("{run_seed}:{node_id}")[:8], 16)`, applied to `random` and to NumPy's global
generator when NumPy is loaded. The seed is part of the cache key.
**Consequences.** Adding or removing other nodes does not change a node's seed. Libraries
with their own generators (PyTorch, JAX, NumPy `Generator` objects) must be seeded by the
node from `current_context().seed`.

## D11. Environment capture without environment variables

**Decision.** Each run records Python version and implementation, platform, NeuroWeave
version, Git commit, branch and dirty flag, and installed package versions. Environment
variables are not recorded.
**Consequences.** Secrets in the environment never enter run records. Differences caused by
environment variables are not detected.

## D12. No sandbox, stated plainly

**Decision.** v0.2.0 does not isolate node code. Documentation, the Studio's project
settings and `nw studio` startup messages say so. Container isolation is deferred with
explicit prerequisites (see the plan).
**Consequences.** Users must trust the node modules they configure, as with any Python
script they run.

## D13. Local-only HTTP API with request-origin checks

**Decision.** `nw studio` binds `127.0.0.1` by default and warns when bound elsewhere. Every
request must carry a local `Host` header (blocks DNS-rebinding), and every state-changing
`/api` request must carry an `X-NeuroWeave-Client` header (a cross-site form or simple
request cannot set it without a CORS preflight, which is never granted). Artifact content
is served with `X-Content-Type-Options: nosniff` and a `sandbox` Content-Security-Policy;
Markdown reports are rendered in an `<iframe sandbox="">` with a restrictive CSP.
**Consequences.** Other software running as the same user can still call the API; there is
no authentication. See [security.md](security.md).

## D14. Optimistic concurrency for workflow edits

**Context.** Two Studio tabs, or a Studio tab and `nw workflows import --force`, could
overwrite each other's edits silently with last-write-wins.
**Decision.** `GET /api/workflows/{id}` returns the workflow's content hash as an `ETag`;
the Studio sends it as `If-Match` with each save; the server answers `409` if the stored
version changed. The Studio pauses editing and offers to reload. Requests without
`If-Match` (CLI, explicit "Restore this version") still overwrite.
**Consequences.** No silent lost updates from the Studio. No merging.

## D15. Studio stack and data flow

**Decision.** React 19 + TypeScript + Vite, Tailwind CSS 4, React Flow 12 for graphs,
TanStack Query for server state, Zustand for UI state. The React Flow model is always
derived from the server's `Workflow` document; local edits are pure functions in
`lib/graph.ts` (unit-tested) and are saved through the API, which returns the kernel's
validation for the saved version. The production build is written into the Python
package so `pip install` ships a working Studio.
**Consequences.** There is one source of truth for graph semantics (the Python kernel);
the frontend has no independent notion of type compatibility beyond structural checks.

## D16. Python 3.11 minimum

**Decision.** `requires-python >= 3.11` (uses `contextlib.chdir`, modern typing). CI tests
3.11 and 3.14.

## D17. Pinned environment lock with each run

**Context.** The name→version package map recorded with each run was not installable
(editable and VCS installs looked like plain versions) and project lockfiles were ignored.
**Decision.** Each run stores a deterministic requirements-format lock in the artifact store
(index packages as `name==version`, VCS and local installs via PEP 610 `direct_url.json`)
plus copies of any project `uv.lock` / `requirements*.txt` / `poetry.lock`. NeuroWeave
itself is excluded from the pinned lines and recorded separately. Reproduction reports
`environment_match` from lock hashes without changing the meaning of *reproduced*.
**Alternatives.** Recording only `uv.lock` (misses the interpreter's actual installs);
`pip freeze` alone (loses VCS/local classification).
**Consequences.** `nw env show` / `nw env export` and isolated rebuild become possible.
Local `file://` packages can only be rebuilt while their paths still exist.

## D18. Isolated reproduction via uv, not a container

**Context.** Users asked for a "reproduced" verdict that means more about the environment.
**Decision.** `nw reproduce --isolated` rebuilds a fresh venv with `uv venv --python` and
`uv pip install --no-deps --no-build -r lock`, installs NeuroWeave specially, caches the
env under `.neuroweave/envs/<lockhash>/`, and runs the worker with that interpreter. Source
builds are refused by default. No Docker for now.
**Alternatives.** Docker/OCI images (stronger isolation, heavier dependency); Nix; full
`uv sync` from the project's lockfile.
**Consequences.** Same OS and architecture required; system libraries are not rebuilt; the
verdict stays exact-content-hash and `environment_match` reports lock equality beside it.
See [reproducibility.md](reproducibility.md#environment-reconstruction).
