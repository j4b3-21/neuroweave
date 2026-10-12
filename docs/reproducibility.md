# Reproducibility in NeuroWeave

NeuroWeave's goal is that every result can be explained (what produced it, from what) and
re-checked (does running it again give the same bytes?). This document states precisely what
is recorded, when results are reused, how reproduction is judged, and what is **not**
detected.

## What every run records

| Record | Where |
|---|---|
| The exact workflow that ran (nodes, types, parameters, connections) | `snapshots/<sha256>.json`, referenced by `runs.snapshot_hash` |
| Run seed, cache setting, trigger (`cli`, `studio`, `reproduce`), timings, status, error | `runs` table |
| Per node: definition id, declared version, source hash, parameters actually used, derived seed, cache key, cache decision, status, duration, error and traceback, log file | `node_executions` table, `runs/<id>/logs/` |
| Every output: content hash, size, serializer, media type, Python type | `artifacts` table and the content-addressed store |
| Every input a node consumed, including external files read through `Path` parameters | `execution_inputs` table, `role="input"` artifacts |
| Metrics logged with `log_metric` (value, step, goal direction) | `metrics` table |
| Environment: Python version and implementation, platform, NeuroWeave version, Git commit/branch/dirty flag, installed packages | `runs.environment` |
| Pinned installable lock (requirements-format text with VCS and local installs classified via PEP 610) and any project `uv.lock` / `requirements*.txt` / `poetry.lock` copies | Content-addressed in the artifact store; hashes in `runs.environment.lock` and `runs.environment.project_lockfiles` |

Environment variables are intentionally not recorded (they often contain secrets).
Inspect a run's lock with `nw env show RUN` or `nw env export RUN -o requirements.txt`.

## Seeds

A run has one seed (`--seed`, the Studio's seed field, or the project's `default_seed`).
Each node gets a seed derived from the run seed and its node id, so a node's randomness does
not change when unrelated nodes are added. Before a node runs, NeuroWeave seeds Python's
`random` module and, if NumPy is already imported, `numpy.random.seed`. Other generators
(NumPy `Generator` instances, PyTorch, JAX, TensorFlow) must be seeded explicitly:

```python
from neuroweave import current_context

rng = numpy.random.default_rng(current_context().seed)
```

## When results are reused (caching)

A node's previous result is reused only if all of the following are identical:

- node id in the workflow and definition id;
- declared `version`;
- SHA-256 of the node function's source code;
- parameter values;
- content hash and serializer of every input;
- the node's derived seed;
- Python implementation and minor version (for example CPython 3.14).

Reuse is always visible: the node execution is marked as a cache hit with the id of the
execution it reused and a note, and the Studio shows the node as "Reused". Before a cached
output is reused, its stored bytes are re-hashed; a mismatch makes the node execute instead.

Disable reuse per node with `@node(cache=False)` (for nodes that read clocks, networks or
unmanaged files) or per run with `nw run --no-cache` / unticking "Reuse cached results".

## Reproduction checks

`nw reproduce RUN` (or **Reproduce** in the Studio) re-executes the original snapshot with
the original seed and caching disabled, using the node code currently installed, and records
a new run linked to the original. The verdict uses the **exact-content-hash** policy:

- **reproduced**: every output the original run recorded has a byte-identical counterpart;
- **not reproduced**: at least one output is missing or differs (the differing outputs are
  listed);
- **failed**: the reproduction run did not succeed;
- **pending**: it is still running.

The report also carries `environment_match` (`identical` / `different` / `unknown`, from the
pinned lock hashes) and `isolated` (true when the run used a rebuilt environment). These do
**not** change the verdict: byte-identical outputs are still *reproduced* even when the
environment differs. Notes state the combination plainly (for example "Outputs are
byte-identical and the reproduction ran in a rebuilt environment whose lock matches the
original").

`nw reproduce --isolated` (or **Reproduce in a rebuilt environment** in the Studio) first
rebuilds a fresh virtual environment from the run's lock with `uv` (same OS and architecture
required; system libraries are not rebuilt), then runs the reproduction inside it. See
[Environment reconstruction](#environment-reconstruction) below.

### What "Reproduced" means, exactly

A **reproduced** verdict states all of the following, and nothing more:

1. The workflow snapshot the original run executed (same content hash) was executed again,
   with the original run seed.
2. It ran **on this machine, in this workspace**, with caching disabled, so every node
   executed rather than being reused.
3. It used the node code and Python packages **installed now**, not the ones the original
   run used.
4. The reproduction run succeeded.
5. Every output the original run recorded has an output with the same node id and port in
   the reproduction whose SHA-256 is equal (byte-identical content).

It does **not** state that:

- the code was unchanged: if a node's source hash or version differs but its outputs are
  identical, the verdict is still *reproduced* and a note names the changed nodes;
- the environment was the same: look at `environment_match` and the environment badge in the
  Studio; differences are also listed as notes, not judged into the verdict;
- the result was reproduced independently on another machine or by another person. Even
  `--isolated` only rebuilds packages on **this** machine. It shows the result **repeats here**;
- a failure was reproduced: for an original run that FAILED, only the outputs it recorded are
  compared, so a reproduction that now succeeds is *reproduced* if those outputs match (a note
  says the original failed). An original that failed before recording any output is *not
  reproduced* (or *failed*, if the reproduction fails as well);
- outputs that only the reproduction produced were checked; they are ignored.

The Studio's verdict text and the environment badge say the same: byte-identical outputs are
*Reproduced*, and the badge reports *Same environment*, *Rebuilt environment*,
*Environment differs* or *Environment unknown* beside it.

## Environment reconstruction

Environment reconstruction is **partial**:

| Rebuilt | Not rebuilt |
|---|---|
| Python version (via `uv venv --python`) | Operating system and architecture (must match) |
| Every package in the pinned lock (`uv pip install --no-deps --no-build`) | System libraries, CUDA, firmware, hardware |
| NeuroWeave itself (from its recorded source, or the currently running tree) | Environment variables (intentionally never recorded) |
| Project lockfiles are archived with the run for inspection | They are not automatically applied by `--isolated` (the run lock is) |

Preconditions: `uv` on PATH, the project trusted, the original run has a lock, and every
`file://` local package path still exists. Source builds are refused by default
(`--allow-build` lifts that). Rebuilt environments are cached under
`.neuroweave/envs/<lockhash[:16]>/` and reused until `--rebuild`.

Verified locally with `NEUROWEAVE_NETWORK_TESTS=1 pytest tests/test_isolated_network.py`: the
demo rebuilds, reproduces, and reports `verdict=reproduced` with `environment_match=identical`.

## Six separate questions

"Is this result reproducible?" bundles six questions with different answers in this
release. Keeping them apart avoids reading more into a green badge than it supports.

| Aspect | Question | Status in v0.2.0 | Evidence and limits |
|---|---|---|---|
| Artifact content integrity | Are the stored bytes the bytes that were recorded? | **Supported** | Content-addressed SHA-256 store; bytes re-hashed before reuse and by `nw verify`. Detects corruption and edits that bypass the database; does not authenticate who wrote them. Inputs above `max_input_snapshot_bytes` are recorded by hash only |
| Workflow snapshot reconstruction | Can the exact workflow that ran be recovered? | **Supported** | Immutable `snapshots/<sha256>.json` per run; the Studio can restore it as the current workflow. The snapshot names node types and parameters; code hashes are recorded per node execution, and the node code itself is not stored |
| Execution provenance | What produced each result, from which inputs, with which code identity and parameters? | **Supported, with blind spots** | Per-node records, input/output hashes, cache decisions and lineage. Blind spots: code outside the node function, undeclared inputs, and cache hits (the reused output was computed by an earlier execution whose environment can differ from the reusing run's, because packages are not part of the cache key) |
| Environment reconstruction | Can the software environment be rebuilt? | **Partial** | A pinned installable lock and project lockfiles are stored with each run. `nw reproduce --isolated` rebuilds Python packages on the same OS/architecture with `uv`; system libraries and hardware are not. See above |
| Independent re-execution | Can someone else, elsewhere, run it again? | **Not supported** | Even `--isolated` runs on this machine. Exporting a bundle for another machine is still on the roadmap |
| Result equivalence | Are two results the same? | **Exact bytes only** | Exact SHA-256 per output. No numerical tolerance, no semantic comparison; pickle bytes can differ for equal objects |

## A richer status model (proposal, not implemented)

The single *reproduced* verdict merges cases a reader would want to tell apart. A future
version could report a status per reproduction such as:

| Status | Meaning |
|---|---|
| `repeated` | Same machine, every node executed, exact hashes match, node code hashes, versions and recorded package versions unchanged |
| `repeated_with_changes` | Exact hashes match, but node code/versions or the environment differ (listed) |
| `partial` | The original run failed; its recorded outputs match, its failure did not recur (or did) |
| `differs` | At least one original output is missing or differs |
| `failed` / `pending` | As today |
| `reproduced_independently` | (Requires the roadmap below.) Re-executed from an exported bundle in a reconstructed environment, ideally on another machine, with exact hashes matching |
| `equivalent` | (Requires tolerance policies.) Outputs match under a declared per-artifact tolerance rather than byte equality |

The verdict and policy names stored today (`reproduced`, `exact-content-hash`) would remain
readable; new statuses would be added beside them, not reinterpret old records.

## Roadmap

In dependency order:

1. **Status model.** Derive `repeated` / `repeated_with_changes` / `partial` from data already
   recorded (code hashes, versions, environment diff, original status); show them in the CLI
   and Studio.
2. **Code capture.** Store the source files of node modules (content-addressed, like
   artifacts) with each run, so the code that ran can be inspected and diffed, not just
   hashed. Record `git diff` when the tree is dirty.
3. **Environment lock and local rebuild.** Done in part: each run stores a pinned lock and
   project lockfiles; `nw reproduce --isolated` rebuilds with `uv` on the same OS. Still open:
   wheel hashes in the lock, applying the project's own `uv.lock` as the install source, and
   recording interpreter build metadata.
4. **Export bundle.** `nw export RUN` writing the snapshot, captured code, lock and stored
   inputs into one archive, with a manifest of hashes.
5. **Independent re-execution.** `nw reproduce --from BUNDLE` on another machine in a fresh
   environment built from the lock; only this may report `reproduced_independently`.
6. **Tolerance policies.** Declared per output type (for example relative tolerance for
   numeric tables), reported as `equivalent`, never merged with exact matches.

## Blind spots (not detected)

These can make a cached result stale or make a reproduction differ without NeuroWeave being
able to tell you why:

1. **Code outside the node function.** The source hash covers only the decorated function.
   Changes to helper functions, other modules or installed libraries are not detected. Bump
   the node's `version` when they change, or run with `--no-cache`.
2. **Undeclared inputs.** Files, databases, URLs or clocks a node reads without receiving
   them as `Path` parameters are not hashed. Declare file inputs as `Path` parameters, or mark
   such nodes `cache=False`.
3. **Package versions are recorded; in-place reproduction does not enforce them.** Caching
   does not compare installed package versions. Plain `nw reproduce` runs with whatever is
   installed now; use `nw reproduce --isolated` to rebuild from the run's lock, or
   `nw compare` / the environment badge to see differences.
4. **Environment rebuild is partial.** `--isolated` rebuilds Python packages on the same OS
   and architecture; it does not rebuild system libraries, CUDA or hardware, and it is not a
   container. Another machine still requires installing the same software yourself.
5. **Large inputs.** External files larger than `max_input_snapshot_bytes` (50 MB by
   default) are hashed but not copied; if the original file changes or disappears, the
   reproduction will report the input change or fail.
6. **Numerical non-determinism.** Multithreaded BLAS, GPU kernels, parallel reductions and
   platform-specific floating point can change the last bits of results. Under the
   exact-hash policy these are reported as not reproduced. Tolerance-based comparison is not
   implemented yet.
7. **Pickled outputs.** Objects without a built-in serializer are pickled; pickle bytes can
   differ across Python versions even when the object is equal.
8. **Environment variables** are not recorded (see above).

## Practical checklist

- Keep node functions pure: take everything as parameters or inputs, return results.
- Pass data files as `Path` parameters so they are hashed and, when small, stored.
- Seed any random generator other than `random` or NumPy's global generator from
  `current_context().seed`.
- Bump `version=` when behaviour changes through code outside the node function.
- Commit your node modules and workflow files to Git; the commit is recorded with each run.
- Use `nw reproduce` before publishing a result, and keep the reproduction run as evidence.
