"""Principal MVP integration test: the deterministic research example, end to end.

Each numbered comment refers to an acceptance check in docs/implementation-plan.md (M8).
"""

from __future__ import annotations

import json
import subprocess
import sys

from neuroweave.experiments import compare_runs, reproduce_run
from neuroweave.kernel import Edge, validate_workflow
from neuroweave.provenance import upstream_lineage
from neuroweave.runtime import load_artifact_value, prepare_run, run_workflow
from neuroweave.store.workspace import Workspace


def test_research_example_end_to_end(demo_project, demo_registry) -> None:
    ws = demo_project
    # 1. The workflow exists in the project (built with the SDK, imported from JSON).
    workflow = ws.load_workflow("rainfall-yield")
    # 2. It validates.
    report = validate_workflow(workflow, demo_registry.catalog())
    assert report.valid, report.issues
    # 3. Invalid connections are rejected (Table output into a dict[str, float] input).
    bad = workflow.model_copy(deep=True)
    bad.edges = [e for e in bad.edges if not (e.target == "report" and e.target_port == "stats")]
    bad.edges.append(Edge(source="transform", source_port="output", target="report",
                          target_port="stats"))
    assert "type_mismatch" in {i.code for i in validate_workflow(bad, demo_registry.catalog())
                               .issues}

    # 4-6. Execution follows dependency order, resolves inputs and records states.
    run = run_workflow(ws, workflow, demo_registry)
    assert run.status == "SUCCEEDED", run.error
    executions = ws.db.node_executions(run.id)
    assert [e.node_id for e in executions] == report.order
    started = [e.started_at for e in executions]
    assert started == sorted(started)
    assert all(e.status == "SUCCEEDED" and e.duration_ms is not None for e in executions)
    stats = load_artifact_value(ws, ws.db.outputs_of(executions[3].id)[0])
    assert stats["n"] == 22.0 and stats["pearson_r"] > 0.99  # 1 incomplete + 1 outlier removed

    # 8-9. Outputs are persisted and their hashes verify.
    outputs = ws.db.list_artifacts(run_id=run.id, role="output")
    assert len(outputs) == 7 and all(ws.artifacts.verify(a.content_hash) for a in outputs)
    report_artifact = next(a for a in outputs if a.node_id == "report")
    text = load_artifact_value(ws, report_artifact).text
    assert "pearson_r | 0.99" in text and "<svg" in text

    # 10. Provenance of the report reaches the input CSV.
    lineage = upstream_lineage(ws, report_artifact.id)
    assert any(n.label == "data/field_trial.csv" for n in lineage.nodes)

    # 7. Failures propagate: break the input and only downstream nodes are affected.
    broken = workflow.model_copy(deep=True)
    broken.node("validate").params["required_columns"] = ["rainfall_mm", "no_such_column"]
    failed = run_workflow(ws, broken, demo_registry)
    states = {e.node_id: e.status for e in ws.db.node_executions(failed.id)}
    assert failed.status == "FAILED"
    assert states["load"] == "SUCCEEDED" and states["validate"] == "FAILED"
    assert {states[n] for n in ("transform", "statistics", "bootstrap", "plot", "report")} == \
        {"SKIPPED"}

    # 11-12. Save, reload and reconstruct after a "restart" (fresh Workspace object and a
    # separate Python process reading the same files).
    reopened = Workspace(ws.root)
    assert reopened.load_workflow("rainfall-yield") == workflow
    assert reopened.load_snapshot(run.snapshot_hash) == workflow
    script = (
        "import json,sys; from neuroweave.store import Workspace; "
        f"ws=Workspace.open(sys.argv[1]); r=ws.db.get_run({run.id!r}); "
        "print(json.dumps({'status': r.status, 'nodes': len(ws.db.node_executions(r.id))}))"
    )
    out = subprocess.run([sys.executable, "-c", script, str(ws.root)], capture_output=True,
                         text=True, check=False)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == {"status": "SUCCEEDED", "nodes": 7}

    # 13. A second run with a changed parameter can be compared with the first.
    changed = workflow.model_copy(deep=True)
    changed.node("transform").params["outlier_z"] = 10.0
    second = run_workflow(ws, changed, demo_registry)
    comparison = compare_runs(ws, run.id, second.id)
    transform = next(n for n in comparison.nodes if n.node_id == "transform")
    assert transform.param_changes == {"outlier_z": (3.0, 10.0)}
    assert not transform.outputs["output"].identical  # outlier kept this time
    assert next(n for n in comparison.nodes if n.node_id == "load").cache_hit == (False, True)

    # 14. Reproducibility uses an explicit policy.
    reproduction = reproduce_run(ws, run.id, demo_registry)
    assert reproduction.verdict == "reproduced"
    assert reproduction.policy.startswith("exact-content-hash")


def test_worker_process_executes_prepared_run(demo_project) -> None:
    run = prepare_run(demo_project, demo_project.load_workflow("rainfall-yield"),
                      trigger="studio")
    completed = subprocess.run(
        [sys.executable, "-m", "neuroweave.runtime.worker", "--workspace",
         str(demo_project.root), "--run-id", run.id],
        capture_output=True, text=True, timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    record = demo_project.db.get_run(run.id)
    assert record.status == "SUCCEEDED" and record.worker_pid is not None
