# Release readiness (v0.2.0, assessed 2026-10-12)

An evidence-based assessment of whether the current `main` can be released, written after the
test-automation, security and reproducibility work recorded in
[implementation-progress.md](implementation-progress.md#session-2026-10-12-test-automation-security-and-release-audit).

Ratings:

- **Verified**: checked in this assessment, with the evidence given.
- **Partially verified**: some of it was checked; the gap is stated.
- **Failed**: checked and not met.
- **Not verified**: not checked (and why).
- **Intentionally deferred**: out of scope for this release, documented as such.

All results are from a MacBook (macOS, arm64) unless marked otherwise. **Nothing has run on
GitHub Actions for these commits**: they have not been pushed (pushing was out of scope), so
every CI statement below is about the workflow file, not about a CI run.

## Summary

NeuroWeave v0.2.0 is in good shape for a **research preview used by people who trust the
projects they open**: every automated check passes locally on Python 3.11 and 3.14, the
Studio is covered end to end in a real browser against real servers, a clean install from
the committed sources works, and the main code-execution risk of opening someone else's
project now requires explicit trust.

It is **not ready for a public release** until three things happen: CI runs green on GitHub
at least once (including the new browser job), a license is chosen, and Python dependencies
are locked. These are owner decisions or require pushing, so they were not done here.

## Build and installation

| Item | Rating | Evidence |
|---|---|---|
| Clean install from committed sources | Verified | `git archive HEAD` into an empty temporary directory, `npm ci` and `npm run build` in `apps/studio`, a fresh `uv venv --python 3.14`, non-editable `uv pip install .`. The installed package contains the built Studio. With that install only: `nw --help`; the README demo (`nw init`, `nw workflows import`, `nw run` twice: first `SUCCEEDED`, second `SUCCEEDED (7 node(s) reused from cache)`); `nw reproduce` gave `Verdict: reproduced`; `nw studio` served `/api/health` (`{"status":"ok","version":"0.2.0"}`) and the UI, and refused a `Sec-Fetch-Site: cross-site` API request with 403; a copied project was refused by `nw nodes` (exit 1, trust message). Trust decisions went to a temporary `NEUROWEAVE_TRUST_FILE` |
| Python 3.11 (minimum supported) | Verified | Fresh `uv venv --python 3.11` (CPython 3.11.15), `uv pip install -e ".[dev]"`: 118 pytest tests pass, `ruff check` clean, and all 12 Playwright tests pass with `NEUROWEAVE_PYTHON` pointing at it |
| Python 3.14 | Verified | Repository `.venv` (CPython 3.14): 118 pytest tests pass |
| Studio production build | Verified | `npm run build`: one JavaScript chunk of 572 kB (177 kB gzipped); Vite warns about the chunk size |
| Wheel/sdist artifacts | Verified | `uv build` in the clean export (after `npm run build`) produced `neuroweave-0.2.0-py3-none-any.whl` (89 files) and `neuroweave-0.2.0.tar.gz` (120 files); both contain `server/static/index.html` and the new `store/trust.py`; the sdist contains no `node_modules`. The UI is included only because `npm run build` ran first (the static directory is git-ignored), so a release build must keep that order |
| Python dependency locking | Failed | `pyproject.toml` has lower bounds only and there is no lockfile, so installs on different days can resolve different versions |
| npm dependency locking and audit | Verified | `package-lock.json` is committed and `npm ci` uses it; `npm audit` reports 0 vulnerabilities (all and production-only) |
| Python dependency vulnerability audit | Not verified | No audit tool (for example `pip-audit`) is installed or configured |
| License | Failed | No `LICENSE` file and no license metadata in `pyproject.toml`. The owner must choose one before any public release |
| Changelog / release notes | Failed | None exist |
| Version tag and release | Intentionally deferred | Out of scope (no tags or releases were to be created). Version is 0.2.0 in `pyproject.toml` and `package.json` |

## Automated tests

| Item | Rating | Evidence |
|---|---|---|
| Python tests | Verified | 118 pass on 3.14 and on 3.11 (about 7 s). Up from 101 at the start of this session: 7 incremental-execution and persistence regression tests (`tests/test_incremental.py`) and 10 security tests (`tests/test_security.py`) |
| Lint | Verified | `ruff check src tests examples` clean |
| Formatting | Partially verified | `ruff format --check` would reformat 30 files; formatting is not enforced in CI (pre-existing) |
| TypeScript | Verified | `npm run typecheck` (app and e2e configurations) clean |
| Studio unit tests | Verified | 8 Vitest tests pass (3 new for node error formatting) |
| Browser end-to-end tests | Verified (Chromium only) | 12 Playwright tests pass (`npm run test:e2e`), also with `CI=1` (two workers, HTML report). Each test uses its own temporary project and `nw studio` process; requests leaving the machine fail the test. Stability: 36 of 36 with `--repeat-each=3` (parallel workers). Firefox and WebKit are not tested |
| Every commit passes on its own | Verified | The full local gate (pytest, `ruff check`, TypeScript, Vitest, `npm run test:e2e`) was re-run on the exported tree of each of the 22 commits from `07d1e3f` to `49ebc54`, each importing its own source; all passed. `7f865a0` (one test file) is covered by the final verification at HEAD. Per-commit counts are in the progress log |
| CI workflow | Not verified | `.github/workflows/ci.yml` parses (PyYAML), has `permissions: contents: read`, and uses action majors whose `action.yml` declares `node24` (checkout v7, setup-python v7, setup-node v7, upload-artifact v7). It has never run for these commits. The new browser job in particular has not run on Ubuntu |

Browser scenarios covered (all against the production build and a real server):

| Scenario | Spec |
|---|---|
| Open a saved workflow; every node and connection rendered | `workflow-editor.spec.ts` |
| Edit a parameter; verified through the API, on disk and after reload | `workflow-editor.spec.ts` |
| Invalid workflow: incompatible connection refused; missing input disables Run; the API refuses to start it (422) | `workflow-editor.spec.ts` |
| Run; run record, snapshot, output hashes recomputed from the store, input file hash | `execution.spec.ts` |
| Incremental rerun: only the edited node and its downstream closure execute; reuse points at the source | `execution.spec.ts` |
| Compare two runs: parameter change, differing outputs, metric deltas | `compare.spec.ts` |
| Reproduce: deterministic run is *reproduced*; a nondeterministic node is *not reproduced* | `reproduction.spec.ts` |
| Failing node: error, traceback, log, downstream skipped | `failure.spec.ts` |
| Page reload and server restart: workflow, runs and artifacts unchanged and verifiable | `persistence.spec.ts` |
| Untrusted project: opened without importing code, runs refused (403), workflow untouched; runs once trusted | `trust.spec.ts` |

Not covered in the browser: dragging nodes from the palette, cancelling a long run, the
concurrent-edit conflict banner, and the artifact preview sandbox. Each has API or unit tests
underneath.

## Security

| Item | Rating | Evidence |
|---|---|---|
| Opening a received project runs its code silently | Verified fixed | Trust gate (`feat(security)`): CLI, interactive prompt, API and browser tests; the marker module is never imported before trust. Projects created with `nw init` never prompt |
| Project files shadowing standard-library modules in helper processes | Verified fixed | `python -P` for catalogue and worker processes; regression test fails without the fix |
| Cross-site browser requests reaching the API (including GETs that import code) | Verified fixed | `Sec-Fetch-Site` check; regression test fails without the fix; the browser suite confirms the Studio's own requests still work |
| `nw logs` reading paths outside the workspace | Verified fixed | Containment check; regression test fails without the fix |
| Repository config (`core.fsmonitor`) running commands while recording Git state | Verified fixed | `-c core.fsmonitor=false`; regression test fails without the fix |
| Host allowlist, custom header, path validation | Verified (pre-existing) | Existing tests in `tests/test_api.py`, `test_workspace.py` and `test_artifacts.py` pass |
| Artifact content isolation headers (`nosniff`, sandboxing CSP) | Verified | Previously untested; assertions added to `tests/test_api.py` (`7f865a0`) |
| Pickles in received workspaces, file parameters naming any path, machine details in run records, git clean filters, path-keyed trust | Intentionally deferred | Documented as known risks in [security.md](security.md#what-is-not-protected-known-risks) |
| Sandbox or isolation for node code | Intentionally deferred | None exists and none is claimed; requirements listed in [security.md](security.md#requirements-for-future-isolation-not-implemented) |
| API authentication against other local processes | Intentionally deferred | Documented; any local process can call the API |

## Reproducibility

| Item | Rating | Evidence |
|---|---|---|
| Artifact content integrity | Verified | Browser tests recompute SHA-256 of stored objects independently; persistence test verifies an artifact after a server restart; `nw verify` tests |
| Workflow snapshot reconstruction | Verified | Browser test checks the stored snapshot equals the workflow that ran and that `snapshot_hash` equals the saved revision |
| Incremental reuse is exact | Verified | `tests/test_incremental.py` (three different edit points, revert, reuse chains, fresh process) and `execution.spec.ts` |
| Meaning of "Reproduced" documented and shown truthfully | Verified | [reproducibility.md](reproducibility.md#what-reproduced-means-exactly); Studio wording corrected (`d094933`), asserted by `reproduction.spec.ts` |
| Environment reconstruction | Partially verified | Each run stores a pinned lock; `nw reproduce --isolated` rebuilds with `uv` on the same OS. Local network e2e (`NEUROWEAVE_NETWORK_TESTS=1`) reported `verdict=reproduced` and `environment_match=identical`. System libraries are not rebuilt; see [reproducibility.md](reproducibility.md#environment-reconstruction) |
| Independent re-execution | Intentionally deferred | Even `--isolated` runs on this machine; export-bundle reproduction is still on the roadmap |
| Tolerance-based equivalence | Intentionally deferred | Exact bytes only |

## Platforms

| Platform | Rating | Evidence |
|---|---|---|
| macOS (arm64) | Verified | Everything above |
| Linux | Not verified | Only through the CI configuration, which has not run for these commits (earlier commits passed the Python and Studio jobs on Ubuntu, per the previous progress log) |
| Windows | Not verified | Never tested; server shutdown and run cancellation rely on POSIX signals and process sessions |

## Before a public release

1. Push the branch and get all three CI jobs green on GitHub (owner action).
2. Choose a license; add `LICENSE` and `license` metadata.
3. Lock Python dependencies (for example `uv.lock`) and add a dependency audit to CI.
4. Add a changelog entry for 0.2.0 / the next version.
5. Build the wheel and sdist once and check that the Studio UI is inside.
