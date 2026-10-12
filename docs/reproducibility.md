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
