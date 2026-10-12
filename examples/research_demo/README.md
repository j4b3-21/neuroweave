# Research demo: rainfall and crop yield

A small, fully deterministic analysis that exercises every part of NeuroWeave: typed nodes,
validation, execution, caching, metrics, stochastic nodes with seeds, figures, reports,
comparison, reproduction and lineage.

**Question.** In a field trial of 24 plots, how strongly does seasonal rainfall predict crop
yield, and how uncertain is the slope?

```text
load ──> validate ──> transform ──┬──> statistics ──┬──> plot ───┐
                                  │                 └───────────┼──> report
                                  └──> bootstrap ───────────────┘
```

| Node | Function | What it does |
|---|---|---|
| `load` | `load_dataset(path: Path) -> Table` | Reads `data/field_trial.csv` (the file is hashed and stored) |
| `validate` | `validate_dataset` | Drops rows with missing values in required columns (plot P09 has no rainfall); logs `rows_dropped` |
| `transform` | `transform_dataset` | Converts units (`cm` or `mm`) and removes yield outliers beyond `outlier_z` standard deviations (plot P18); logs `outliers_removed` |
| `statistics` | `compute_statistics` | Least-squares slope and intercept, Pearson r, R²; logs `pearson_r` and `r_squared` |
| `bootstrap` | `bootstrap_slope` | Percentile bootstrap confidence interval for the slope using `random` (seeded per node); logs `slope_ci_width` |
| `plot` | `plot_relationship` | Deterministic SVG scatter plot with the fitted line |
| `report` | `write_report` | Markdown report embedding the statistics, interval and figure |

Files: `demo_nodes.py` (the nodes), `data/field_trial.csv` (input),
`build_workflow.py` (builds the graph with the Python `WorkflowBuilder` and writes
`workflow.json`).

## Walkthrough

```bash
cp -R examples/research_demo /tmp/nw-demo && cd /tmp/nw-demo
nw init --name "Rainfall and yield" -m demo_nodes
nw workflows import workflow.json
nw validate rainfall-yield
```

**Run, then run again.** The second run executes nothing: every node is reused from the cache
and recorded as a cache hit.

```bash
nw run rainfall-yield
nw run rainfall-yield
nw runs
nw show <run-id>
```

**Change one parameter.** In the Studio (`nw studio`), select the *Bootstrap Slope* node and
set `resamples` to 300, then press **Run**. Only `bootstrap` and `report` execute; the others
are reused. Compare the two runs:

```bash
nw compare <first-run-id> <latest-run-id>
```

The comparison lists the parameter change, shows that only the bootstrap and report outputs
differ, and reports the change in `slope_ci_width`.

**Reproduce.** Re-execute a run from scratch with the same snapshot and seed:

```bash
nw reproduce <run-id>
```

All seven outputs, including the stochastic bootstrap interval, are byte-identical, so the
verdict is `reproduced`.

**Trace the report back to its data.**

```bash
nw artifacts                       # find the report artifact id
nw lineage <report-artifact-id>    # report <- plot, statistics, bootstrap <- ... <- field_trial.csv
nw artifact <report-artifact-id> -o report.md
```

**Detect tampering.** Edit any file under `.neuroweave/artifacts/objects/` and run
`nw verify --all`; the modified artifact is reported, and the next run recomputes the node
instead of reusing the corrupted result.

## Regenerating the workflow file

```bash
python build_workflow.py
```

The repository's end-to-end test (`tests/test_end_to_end.py`) checks the same steps through
the Python API, and `tests/test_cli.py` exercises the commands.
