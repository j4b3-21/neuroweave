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

Environment variables are intentionally not recorded (they often contain secrets).

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

The report also notes when node code or versions differ from the original, when external
inputs changed, and when the environment differs, because any of these can explain a
mismatch.

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
- the environment was the same: differences are listed as notes, not judged;
- the result was reproduced independently (another machine, another person, a reconstructed
  environment). It shows the result **repeats here**;
- a failure was reproduced: for an original run that FAILED, only the outputs it recorded are
  compared, so a reproduction that now succeeds is *reproduced* if those outputs match (a note
  says the original failed). An original that failed before recording any output is *not
  reproduced* (or *failed*, if the reproduction fails as well);
- outputs that only the reproduction produced were checked; they are ignored.

The Studio's verdict text and the note under it say the same: "byte-identical outputs (equal
SHA-256) for every output of the original run" and "the original environment is not
recreated, so a match shows the result repeats here; it is not an independent reproduction."

## Six separate questions

"Is this result reproducible?" bundles six questions with different answers in this
release. Keeping them apart avoids reading more into a green badge than it supports.

| Aspect | Question | Status in v0.2.0 | Evidence and limits |
|---|---|---|---|
| Artifact content integrity | Are the stored bytes the bytes that were recorded? | **Supported** | Content-addressed SHA-256 store; bytes re-hashed before reuse and by `nw verify`. Detects corruption and edits that bypass the database; does not authenticate who wrote them. Inputs above `max_input_snapshot_bytes` are recorded by hash only |
| Workflow snapshot reconstruction | Can the exact workflow that ran be recovered? | **Supported** | Immutable `snapshots/<sha256>.json` per run; the Studio can restore it as the current workflow. The snapshot names node types and parameters; code hashes are recorded per node execution, and the node code itself is not stored |
| Execution provenance | What produced each result, from which inputs, with which code identity and parameters? | **Supported, with blind spots** | Per-node records, input/output hashes, cache decisions and lineage. Blind spots: code outside the node function, undeclared inputs, and cache hits (the reused output was computed by an earlier execution whose environment can differ from the reusing run's, because packages are not part of the cache key) |
| Environment reconstruction | Can the software environment be rebuilt? | **Recorded, not reconstructable** | Python version, platform, NeuroWeave version, installed package versions, Git commit/branch/dirty flag. No lockfile or wheel hashes, no diff of uncommitted changes, no copy of node module source; nothing recreates the environment |
| Independent re-execution | Can someone else, elsewhere, run it again? | **Not supported** | `nw reproduce` runs in the same workspace with current code. Copying a project and reinstalling packages by hand is possible but nothing checks that the environment matches |
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
3. **Environment lock.** Record a lockfile-grade description of the environment (exact
   distributions with hashes, e.g. from `uv pip freeze` or a `uv.lock`) and the interpreter
   build.
4. **Export bundle.** `nw export RUN` writing the snapshot, captured code, lock and stored
   inputs into one archive, with a manifest of hashes.
5. **Independent re-execution.** `nw reproduce --from BUNDLE` in a fresh environment built
   from the lock, recording which machine and environment it ran in; only this may report
   `reproduced_independently`.
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
3. **Package versions are recorded, not enforced.** Caching does not compare installed
   package versions, and reproduction runs with whatever is installed now. Use `nw compare`
   or the reproduction notes to see environment differences, and pin dependencies in your
   project.
4. **Environment is recorded, not recreated.** There is no container or lockfile restore.
   Reproducing on another machine requires installing the same software yourself.
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
