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
| M9 Release readiness | Assessed: research preview yes, public release not yet | [release-readiness.md](release-readiness.md); README, `docs/architecture.md`, `docs/reproducibility.md`, `docs/security.md`, `.github/workflows/ci.yml` |
| M10 Browser tests, security hardening, audits | Done locally; CI not yet run | Session 2026-10-12 below |

### Test results

- Python: 118 tests pass on CPython 3.14 (repository `.venv`) and 3.11.15 (fresh `uv` venv)
  (`pytest -q`, about 7 s); `ruff check` clean.
- Studio: TypeScript typecheck clean (app and e2e); 8 Vitest tests pass; production build
  succeeds (one 572 KB JavaScript chunk, 177 KB gzipped).
- Browser: 12 Playwright tests pass in Chromium (`npm run test:e2e`), with Python 3.14 and
  with 3.11.
- GitHub Actions: the Python 3.11, Python 3.14 and Studio jobs passed for the commits up to
  `3a13d52`. **The commits of the 2026-10-12 session have not been pushed, so neither those
  jobs nor the new browser job have run for them.**
- All tests use temporary directories and make no network calls; the browser tests fail on
  any request that leaves the machine.

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

## Session 2026-10-12: test automation, security and release audit

Goals: browser end-to-end tests against real servers, regression tests for incremental
execution, a CI browser job, current GitHub Actions versions, a security audit, a
reproducibility audit and a release-readiness assessment.

Outcome:

- **Browser tests** (`apps/studio/e2e/`, Playwright, Chromium): 12 tests covering opening,
  editing and validating workflows, running, incremental reuse, comparison, reproduction
  (both verdicts), a failing node, reload and server restart, and an untrusted project. Each
  test creates a temporary project and its own `nw studio`; no mocks, no fixed sleeps,
  traces on failure.
- **Python regression tests**: `tests/test_incremental.py` (7) and `tests/test_security.py`
  (10).
- **CI**: action majors moved to the `node24` releases; new browser job with failure
  artifacts and read-only permissions. Not yet run (not pushed).
- **Security**: opening a project now requires trust before its code is imported (projects
  created with `nw init` are trusted automatically). The helper processes ignore project
  files shadowing standard-library modules, cross-site browser requests are refused,
  `nw logs` stays inside the workspace, and Git no longer runs `core.fsmonitor` from a
  project's repository config. See [security.md](security.md).
- **Reproducibility**: the exact meaning of "Reproduced", six separate aspects, a proposed
  status model and a roadmap in [reproducibility.md](reproducibility.md); the Studio's
  verdict text no longer overclaims.
- **Release readiness**: [release-readiness.md](release-readiness.md), including a clean
  install from the committed sources and a wheel/sdist check.

Defects found and fixed:

- Node errors were shown as "RuntimeError: RuntimeError: …", and skipped nodes as
  "null: Skipped …" (found by the failure scenario).
- Canvas nodes, connections and ports had no accessible names.
- The reproduction verdict claimed more than a same-machine re-execution shows.
- Opening a received project imported its node code without confirmation, including from a
  plain GET of the node catalogue.
- A project file named like a standard-library module (for example `argparse.py`) was
  executed by the catalogue process even with no node modules configured.
- Cross-site pages could make the browser call the API (GETs were not protected).
- `nw logs` followed log paths outside the workspace.
- `git status` while recording a run's environment ran `core.fsmonitor` from the project's
  repository config.
- The Studio showed catalogue-wide errors as "Module '*' failed".

### Commits

Hashes are recorded after the fact: a commit cannot contain its own hash, so this table is
written in a later commit and lists every commit before it. The commit that adds this table
(`docs(release): …`) is not listed here; its hash is in `git log`.

"Re-run" is the full local gate executed afterwards on the exported tree of each commit on
its own (pytest, `ruff check`, TypeScript, Vitest, `npm run test:e2e`), which shows each
commit passes independently.

Every re-run also passed `ruff check` and the TypeScript typecheck; the counts are pytest /
Vitest / Playwright tests passed.

| Commit hash | Commit message | Scope | Tests executed | Result | Remaining follow-up |
|---|---|---|---|---|---|
| `07d1e3f` | test(studio): add Playwright test infrastructure | e2e fixtures and helpers, Playwright config, npm scripts, `.gitignore` | Re-run: 101 / 5 / 1 | Pass | Run in CI |
| `eca4270` | fix(studio): give canvas nodes, connections and ports accessible names | `WorkflowView.tsx`, `NodeCard.tsx` | Re-run: 101 / 5 / 1 | Pass | None |
| `cae6fc1` | test(studio): cover workflow parameter editing and validation | `workflow-editor.spec.ts` | Re-run: 101 / 5 / 4 | Pass | Palette drag-and-drop not covered |
| `c05804c` | test(studio): cover workflow execution and incremental reuse | `execution.spec.ts` | Re-run: 101 / 5 / 6 | Pass | None |
| `f901955` | test(studio): cover experiment comparison | `compare.spec.ts` | Re-run: 101 / 5 / 7 | Pass | None |
| `d094933` | fix(studio): state what a reproduction verdict does and does not show | `RunDetail.tsx` | Re-run: 101 / 5 / 7 | Pass | Status model (reproducibility roadmap) |
| `0ab2dc1` | test(studio): cover reproduction verification | `reproduction.spec.ts`, nondeterministic fixture | Re-run: 101 / 5 / 9 | Pass | None |
| `c1a36a4` | fix(studio): show node errors without a repeated or "null" type prefix | `format.ts` (+ unit tests), inspector, bottom panel, run page | Re-run: 101 / 8 / 9 | Pass | None |
| `412bdd7` | test(studio): cover execution failure | `failure.spec.ts`, failure fixture | Re-run: 101 / 8 / 10 | Pass | None |
| `8d93716` | test(studio): cover persistence across reload and server restart | `persistence.spec.ts` | Re-run: 101 / 8 / 11 | Pass | None |
| `5dd8d64` | test(execution): cover incremental cache invalidation by node identity | `tests/test_incremental.py` | Re-run: 108 / 8 / 11 | Pass | None |
| `acce789` | ci: update deprecated GitHub Actions versions | `ci.yml` | Re-run: 108 / 8 / 11; YAML parsed; `action.yml` of each major checked for `node24` | Pass locally; CI not run | Push to run CI |
| `bcb74d5` | ci: add Playwright browser test job | `ci.yml` | Re-run: 108 / 8 / 11; YAML parsed | Pass locally; CI not run | Push to run CI |
| `5fcbf84` | fix(server): keep project files off the import path of catalog and worker processes | `services.py`, `tests/test_security.py` | Test failed without the fix; re-run: 109 / 8 / 11 | Pass | None |
| `b180292` | fix(server): refuse API requests that browsers mark as cross-site | `app.py`, `tests/test_security.py` | Test failed without the fix; re-run: 110 / 8 / 11 | Pass | Browsers without `Sec-Fetch-Site` (documented) |
| `84568f8` | feat(security): ask before importing code from a project that is not trusted | `store/trust.py`, CLI, server, workspace, Studio wording, Python and browser tests | Gate tests failed with the gate disabled; re-run: 116 / 8 / 12 | Pass | Path-keyed trust; API token (security roadmap) |
| `fa035b6` | fix(cli): keep nw logs inside the workspace | `cli.py`, `tests/test_security.py` | Test failed without the fix; re-run: 117 / 8 / 12 | Pass | None |
| `dbff35d` | fix(runtime): do not let repository config run commands while recording git state | `environment.py`, `tests/test_security.py` | Test failed without the fix; re-run: 118 / 8 / 12 | Pass | Git clean filters (documented) |
| `24f47be` | docs(security): document project trust, the new hardening and known risks | `security.md`, README | Re-run: 118 / 8 / 12 | Pass | None |
| `768a82e` | docs(reproducibility): define what Reproduced means and separate six aspects | `reproducibility.md` | Re-run: 118 / 8 / 12 | Pass | Implement the status model |
| `49ebc54` | docs: describe the browser test suite in the README | README | Re-run: 118 / 8 / 12; 21 relative links checked | Pass | None |
| `7f865a0` | test(server): assert the isolation headers on artifact content | `tests/test_api.py` | At commit: `test_api.py` 6 passed, ruff. Final verification at this commit: 118 (3.14) and 118 (3.11) / 8 / 12, CI mode 12, `--repeat-each=3` 36 | Pass | None |

## Known gaps and risks

- No sandbox (documented in `docs/security.md`); this is the largest risk for anyone running
  shared workflows. Trust is a confirmation step, not isolation.
- The 2026-10-12 commits have not run in CI; the browser job has never run on Ubuntu.
- No license and no Python lockfile (see [release-readiness.md](release-readiness.md)).
- Interactions without browser tests: dragging nodes from the palette, the concurrent-edit
  conflict banner, cancelling a long run and the artifact preview sandbox. They have unit or
  API tests underneath. Browser tests run in Chromium only.
- `ruff format --check` would reformat 30 files; formatting is not enforced.
- The Studio bundle is a single 570 KB chunk; acceptable for a local tool, but code
  splitting (for example lazy-loading the artifact and runs views) would speed first load.
- No garbage collection for artifact blobs or snapshots that are no longer referenced.
- Run history has no pagination beyond the API's `limit` parameter.

## Session: environment lock and isolated reproduction

| Commit | Message | Scope | Tests | Result |
|---|---|---|---|---|
| `5123014` | feat(runtime): record a pinned environment lock and project lockfiles with each run | `environment.py`, executor | `test_environment_lock.py` + related | pass |
| `7b703a1` | feat(experiments): report whether a reproduction ran in the same environment | `experiments.py` | `test_provenance_experiments.py` | pass |
| `a18a4f6` | feat(runtime): rebuild a run's environment with uv | `runtime/isolated.py` | `test_isolated.py` (fake runner) | pass |
| `50750a5` | feat(cli): add nw reproduce --isolated and nw env show/export | `cli.py` | `test_cli.py` | pass |
| `3933080` | feat(server): support isolated reproduction from the API | `server/` | `test_api.py` | pass |
| `ece2d53` | feat(studio): show the environment match and offer reproduction in a rebuilt environment | Studio | Vitest 12, Playwright 12 | pass |
| `cf4d061` | test(runtime): add opt-in network e2e for isolated reproduction | network e2e | `NEUROWEAVE_NETWORK_TESTS=1` once locally: reproduced + identical | pass |
| `eb0222d` | docs: document environment locks, isolated reproduction and their limits | docs | — | — |

## Session: onboarding tutorial and Studio tour

| Commit | Message | Scope | Tests | Result |
|---|---|---|---|---|
| `96ff195` | feat(tutorial): bundle the sample project used by the tutorial | `tutorial/assets`, `ProjectConfig.tutorial` | drift test | pass |
| `1df2956` | feat(cli): add nw tutor, a guided terminal walkthrough | `tutorial/walkthrough.py` | `test_tutor.py` | pass |
| `bed3fa4` | feat(cli): offer the tutorial once on first interactive use | `onboarding.py` | `test_onboarding.py` | pass |
| `4bcce34` | feat(studio): add a guided tour with data-tour anchors | `apps/studio/src/tour/` | Vitest 16 | pass |
| `d7aefc8` | test(studio): cover the guided tour and welcome dialog | Playwright `tour.spec.ts` | Playwright 18 | pass |

## Next highest-priority tasks

1. **Run CI on GitHub** for these commits (push a branch; owner action) and fix anything the
   Ubuntu runners reveal, especially in the browser job.
2. **Release prerequisites**: choose a license; lock Python dependencies (`uv.lock`) and add
   a dependency audit to CI; start a changelog.
3. **Reproduction status model** (`repeated`, `repeated_with_changes`, `partial`) from data
   already recorded; see [reproducibility.md](reproducibility.md#roadmap).
4. **Code capture**: store node module sources with each run so the code that ran can be
   inspected, not just hashed.
5. **Remaining browser coverage**: palette drag-and-drop, the conflict banner, cancelling a
   run, artifact previews; Firefox and WebKit projects.
6. **Security follow-ups**: a per-session API token for the Studio; a warning in the Studio
   for file parameters outside the project; a scrub step before sharing a workspace.
7. **Container isolation** for runs, meeting the requirements listed in
   [security.md](security.md#requirements-for-future-isolation-not-implemented).
8. **Tolerance-based reproduction**, **parallel execution**, **storage maintenance**
   (`nw gc`), and adopting `ruff format` in one mechanical commit.
