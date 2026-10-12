"""Incremental execution checked by node identity, and persistence of history and cache.

``test_cache.py`` counts which node functions were called; these tests check the recorded
links instead (which execution and artifact each reused result came from), that later runs
never modify earlier run records, and that reuse works from a fresh process.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest

from neuroweave.experiments import reproduce_run
from neuroweave.kernel.planning import downstream
from neuroweave.runtime import prepare_run, run_workflow
from neuroweave.store.db import ArtifactRecord, NodeExecutionRecord
from neuroweave.store.workspace import Workspace

WORKFLOW = "rainfall-yield"


def executions(ws: Workspace, run_id: str) -> dict[str, NodeExecutionRecord]:
    return {e.node_id: e for e in ws.db.node_executions(run_id)}


def output(ws: Workspace, execution: NodeExecutionRecord) -> ArtifactRecord:
    (artifact,) = ws.db.outputs_of(execution.id)
    return artifact


def persisted(ws: Workspace, run_id: str) -> dict[str, Any]:
    """Everything recorded about a run, read back from SQLite."""
    db = ws.db
    nodes = db.node_executions(run_id)
    return {
        "run": db.get_run(run_id),
        "executions": nodes,
        "inputs": {e.id: db.inputs_of(e.id) for e in nodes},
        "outputs": {e.id: db.outputs_of(e.id) for e in nodes},
        "metrics": db.metrics_for_run(run_id),
        "artifacts": db.list_artifacts(run_id=run_id, limit=10_000),
    }


# Each change alters the edited node's output, so everything downstream must re-execute too.
@pytest.mark.parametrize(("node_id", "param", "value"), [
    ("bootstrap", "resamples", 300),
    ("transform", "outlier_z", 10.0),
    ("plot", "width", 800),
])
def test_parameter_change_reexecutes_exactly_the_downstream_closure(
    demo_project, demo_registry, node_id, param, value,
) -> None:
    ws = demo_project
    workflow = ws.load_workflow(WORKFLOW)
    first = run_workflow(ws, workflow, demo_registry)
    changed = workflow.model_copy(deep=True)
    changed.node(node_id).params[param] = value
    second = run_workflow(ws, changed, demo_registry)
    assert first.status == second.status == "SUCCEEDED"

    affected = {node_id} | downstream(changed, {node_id})
    a, b = executions(ws, first.id), executions(ws, second.id)
    assert {n for n, e in b.items() if not e.cache_hit} == affected
    for name, execution in b.items():
        previous = output(ws, a[name])
        current = output(ws, execution)
        if name in affected:
            assert execution.cache_source_id is None
            assert current.reused_from is None
            assert execution.cache_key != a[name].cache_key
        else:
            assert execution.cache_source_id == a[name].id
            assert execution.cache_key == a[name].cache_key
            assert current.reused_from == previous.id
            assert current.content_hash == previous.content_hash
            assert current.id != previous.id and current.run_id == second.id
    assert b[node_id].params[param] == value
    assert a[node_id].params[param] != value


def test_earlier_run_records_are_never_modified(demo_project, demo_registry) -> None:
    ws = demo_project
    workflow = ws.load_workflow(WORKFLOW)
    first = run_workflow(ws, workflow, demo_registry)
    before = persisted(ws, first.id)

    changed = workflow.model_copy(deep=True)
    changed.node("bootstrap").params["resamples"] = 300
    run_workflow(ws, changed, demo_registry)
    run_workflow(ws, workflow, demo_registry, use_cache=False)
    reproduce_run(ws, first.id, demo_registry)

    assert persisted(ws, first.id) == before
    assert all(ws.artifacts.verify(a.content_hash) for a in before["artifacts"] if a.stored)
    assert ws.load_snapshot(first.snapshot_hash) == workflow


def test_reverting_a_parameter_reuses_the_original_results(demo_project, demo_registry) -> None:
    ws = demo_project
    workflow = ws.load_workflow(WORKFLOW)
    first = run_workflow(ws, workflow, demo_registry)
    changed = workflow.model_copy(deep=True)
    changed.node("bootstrap").params["resamples"] = 300
    run_workflow(ws, changed, demo_registry)
    reverted = run_workflow(ws, workflow, demo_registry)

    assert reverted.snapshot_hash == first.snapshot_hash
    original = executions(ws, first.id)
    for name, execution in executions(ws, reverted.id).items():
        assert execution.cache_hit, name
        assert execution.cache_source_id == original[name].id, name


def test_reuse_of_a_reused_result_points_to_the_execution_that_computed_it(
    demo_project, demo_registry,
) -> None:
    ws = demo_project
    workflow = ws.load_workflow(WORKFLOW)
    runs = [run_workflow(ws, workflow, demo_registry) for _ in range(3)]
    first, second, third = (executions(ws, r.id) for r in runs)
    for name, execution in third.items():
        assert execution.cache_source_id == first[name].id
        # Artifact records form a chain back to the bytes that were actually computed.
        artifact = output(ws, execution)
        assert artifact.reused_from == output(ws, second[name]).id
        assert ws.db.get_artifact(artifact.reused_from).reused_from == output(ws, first[name]).id


def test_history_and_cache_survive_a_process_restart(demo_project, demo_registry) -> None:
    ws = demo_project
    workflow = ws.load_workflow(WORKFLOW)
    first = run_workflow(ws, workflow, demo_registry)
    recorded = persisted(ws, first.id)

    # A new process with a fresh Workspace and freshly imported node modules: its history comes
    # only from disk, and identical work is still recognised and reused.
    reopened = Workspace(ws.root)
    assert persisted(reopened, first.id) == recorded
    pending = prepare_run(reopened, reopened.load_workflow(WORKFLOW), trigger="studio")
    completed = subprocess.run(
        [sys.executable, "-m", "neuroweave.runtime.worker", "--workspace", str(ws.root),
         "--run-id", pending.id],
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert completed.returncode == 0, completed.stderr

    again = Workspace(ws.root)
    assert again.db.get_run(pending.id).status == "SUCCEEDED"
    assert again.db.get_run(pending.id).worker_pid not in (None, first.worker_pid)
    original = executions(again, first.id)
    for name, execution in executions(again, pending.id).items():
        assert execution.cache_hit, name
        assert execution.cache_source_id == original[name].id, name
    assert persisted(again, first.id) == recorded
