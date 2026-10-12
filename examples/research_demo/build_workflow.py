"""Build the example workflow with the Python SDK and write it to ``workflow.json``.

Run from this directory: ``python build_workflow.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import demo_nodes as n  # noqa: E402

from neuroweave import WorkflowBuilder  # noqa: E402
from neuroweave.kernel import dump_workflow  # noqa: E402


def build():
    b = WorkflowBuilder(
        "rainfall-yield",
        name="Rainfall and crop yield",
        description="Load a field-trial CSV, clean it, quantify the rainfall/yield "
        "relationship, plot it and write a report.",
    )
    raw = b.add(n.load_dataset, id="load", path="data/field_trial.csv")
    valid = b.add(n.validate_dataset, id="validate", data=raw)
    clean = b.add(n.transform_dataset, id="transform", data=valid, rainfall_unit="cm")
    stats = b.add(n.compute_statistics, id="statistics", data=clean)
    interval = b.add(n.bootstrap_slope, id="bootstrap", data=clean, resamples=500)
    figure = b.add(n.plot_relationship, id="plot", data=clean, stats=stats)
    b.add(n.write_report, id="report", stats=stats, interval=interval, figure=figure)
    return b.build()


if __name__ == "__main__":
    (HERE / "workflow.json").write_text(dump_workflow(build()), encoding="utf-8")
    print(f"Wrote {HERE / 'workflow.json'}")
