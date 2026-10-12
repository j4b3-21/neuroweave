from __future__ import annotations

import json

import pytest

from neuroweave.kernel import NodeInstance, Workflow
from neuroweave.runtime import prepare_run
from neuroweave.store.workspace import Workspace, WorkspaceNotFoundError


def test_open_searches_parents(workspace) -> None:
    nested = workspace.root / "a" / "b"
    nested.mkdir(parents=True)
    assert Workspace.open(nested).root == workspace.root


def test_open_without_workspace_fails(tmp_path) -> None:
    with pytest.raises(WorkspaceNotFoundError, match="nw init"):
        Workspace.open(tmp_path)


def test_workflow_crud_and_atomic_files(workspace) -> None:
    wf = Workflow(id="study", name="Study", nodes=[NodeInstance(id="n", type="m:f")])
    workspace.save_workflow(wf)
    assert [w.id for w in workspace.list_workflows()] == ["study"]
    assert workspace.load_workflow("study") == wf
    assert not list(workspace.workflows_dir.glob(".*.tmp"))
    workspace.delete_workflow("study")
    assert workspace.list_workflows() == []
    with pytest.raises(ValueError):
        workspace.load_workflow("../escape")


def test_snapshots_are_immutable_and_verified(workspace) -> None:
    wf = Workflow(id="study", name="Study")
    digest = workspace.write_snapshot(wf)
    assert workspace.load_snapshot(digest) == wf
    path = workspace.snapshots_dir / f"{digest}.json"
    data = json.loads(path.read_text())
    data["name"] = "tampered"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="integrity"):
        workspace.load_snapshot(digest)


def test_legacy_graph_json_imported_once_without_modification(tmp_path) -> None:
    root = tmp_path / "legacy"
    (root / ".neuroweave").mkdir(parents=True)
    legacy = root / ".neuroweave" / "graph.json"
    content = json.dumps({"schema_version": 1, "nodes": [{"id": "a", "type": "m:f"}],
                          "edges": []})
    legacy.write_text(content)
    ws = Workspace(root)
    assert ws.load_workflow("main").nodes[0].id == "a"
    assert legacy.read_text() == content


def test_records_survive_reopen(workspace) -> None:
    run = prepare_run(workspace, Workflow(id="wf", name="wf"))
    reopened = Workspace(workspace.root)
    assert reopened.db.get_run(run.id) == run
    assert reopened.load_snapshot(run.snapshot_hash).id == "wf"


def test_stale_runs_are_reconciled(workspace) -> None:
    run = prepare_run(workspace, Workflow(id="wf", name="wf"))
    workspace.db.update_run(run.id, status="RUNNING", worker_pid=999_999)
    repaired = workspace.db.reconcile_stale_runs(lambda pid: False)
    assert repaired == [run.id]
    record = workspace.db.get_run(run.id)
    assert record.status == "FAILED" and "exited unexpectedly" in record.error
