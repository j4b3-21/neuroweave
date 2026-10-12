# Implementation progress

Status of the milestones in [implementation-plan.md](implementation-plan.md). Updated at the
end of each working session.

## Current status (2026-10-12, v0.2.0)

| Milestone | Status | Evidence |
|---|---|---|
| M0 Audit and planning | Done | `docs/architecture-audit.md`, `docs/implementation-plan.md`, `docs/decisions.md` |
| M1 Graph kernel and SDK | Done | `src/neuroweave/kernel`, `src/neuroweave/sdk`; `tests/test_types.py`, `test_sdk.py`, `test_graph.py` |
| M2 Local execution runtime | Done | `runtime/executor.py`, `worker.py`; `tests/test_runtime.py` |
| M3 Artifacts and provenance | Done | `store/artifacts.py`, `store/db.py`, `provenance.py`; `tests/test_artifacts.py`, `test_provenance_experiments.py` |
| M4 Persistence and reconstruction | Done | `store/workspace.py`; `tests/test_workspace.py`, restart check in `test_end_to_end.py` |
| M5 Experiments and reproducibility | Done | `runtime/cache.py`, `runtime/environment.py`, `experiments.py`; `tests/test_cache.py`, `test_provenance_experiments.py` |
| M6 CLI | Done | `cli.py`; `tests/test_cli.py` |
| M7 API and Studio | Done | `server/`, `apps/studio`; `tests/test_api.py`, `apps/studio/src/lib/graph.test.ts`, manual browser verification (below) |
| M8 End-to-end demonstration | Done | `examples/research_demo`; `tests/test_end_to_end.py` (15 acceptance checks, including a worker-process run) |
| M9 Release readiness | Done, except publishing a release | README, `docs/architecture.md`, `docs/reproducibility.md`, `docs/security.md`, `.github/workflows/ci.yml` |

### Test results

- Python: 101 tests pass on CPython 3.14 and 3.11 locally (`pytest -q`, about 5 s);
  `ruff check` clean.
- GitHub Actions (Ubuntu): the Python 3.11, Python 3.14 and Studio jobs pass.
- Studio: TypeScript strict typecheck clean; 5 Vitest tests pass; production build succeeds
  (one 570 KB JavaScript chunk, 176 KB gzipped).
- All tests use temporary directories and make no network calls.

### Manual Studio verification

Performed against a copy of the research demo served by `nw studio`:

- The editor loaded the workflow, the node catalog (7 definitions in 5 categories) and the
  latest CLI run; validation reported the workflow valid.
- Selecting a node showed its definition, code hash, typed inputs with generated fields,
  connected inputs and last-run outputs.
- Changing `resamples` from 500 to 300 autosaved to `.neuroweave/workflows/rainfall-yield.json`
  (checked on disk).
- Running from the Studio executed only `bootstrap` and `report`; the other five nodes were
  shown as reused with the source execution recorded.
- Comparing the two runs listed the parameter change, byte-identical outputs for unaffected
  nodes, differing outputs for `bootstrap` and `report`, and metric deltas with goal
  direction.
- Reproducing the Studio run produced the verdict "Reproduced: every output is
  byte-identical" (7 of 7 outputs).
- The report artifact rendered inside a sandboxed iframe with its embedded figure, and its
  lineage graph showed 15 records back to `data/field_trial.csv`.

Defects found during verification and fixed in this session:

- Default SDK layout overlapped tall nodes (row spacing increased).
- Two editors on one workflow could overwrite each other silently; saves now use
  `ETag`/`If-Match` and the Studio shows a conflict with a reload action (decision D14).
- URL hash navigation and the browser Back button did not change views.
- A pending reproduction reported spurious code and environment differences, and the
  Studio's verdict did not refresh when the reproduction finished.
- The production Host allowlist included the test client's `testserver` name.

## Known gaps and risks

- No sandbox (documented in `docs/security.md`); this is the largest risk for anyone running
  shared workflows.
- Interactions verified manually only: dragging and connecting nodes in the canvas, the
  conflict banner and cancelling a long run from the Studio. These have unit or API tests
  underneath (graph helpers, conflict API, cancellation in `test_api.py`), but no browser
  end-to-end tests exist yet.
- The Studio bundle is a single 570 KB chunk; acceptable for a local tool, but code
  splitting (for example lazy-loading the artifact and runs views) would speed first load.
- No garbage collection for artifact blobs or snapshots that are no longer referenced.
- Run history has no pagination beyond the API's `limit` parameter.

## Next highest-priority tasks

1. **Browser end-to-end tests** (Playwright) for editing, connecting, running, cancelling and
   comparing in the Studio, run in CI.
2. **Container isolation** for runs (deferred feature with prerequisites met by the worker
   protocol): read-only project mount, no network by default, resource limits.
3. **Tolerance-based reproduction** for floating-point outputs, configurable per node or
   output.
4. **Parallel execution** of independent nodes in the worker.
5. **Storage maintenance**: `nw gc` for unreferenced blobs and snapshots, run deletion.
