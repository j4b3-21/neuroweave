"""Trust boundaries of opening a project: what may run code, and when."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from neuroweave.cli import app
from neuroweave.kernel.serialization import load_workflow
from neuroweave.runtime.environment import git_info
from neuroweave.server.app import create_app
from neuroweave.store.trust import is_trusted, revoke_project, trust_project
from neuroweave.store.workspace import Workspace

HEADERS = {"X-NeuroWeave-Client": "test"}


def wait_for(client: TestClient, run_id: str, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()["run"]
        if run["status"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            return run
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} did not finish")


def marker_module(path: Path, marker: Path, *, fail: bool = False) -> None:
    """A Python file whose only effect on import is to create ``marker``."""
    path.write_text(f"import pathlib\npathlib.Path({str(marker)!r}).write_text('imported')\n"
                    + ("raise SystemExit(3)\n" if fail else ""), encoding="utf-8")


def test_project_files_named_like_stdlib_modules_are_not_imported(tmp_path) -> None:
    project = tmp_path / "project"
    Workspace.init(project)
    marker = tmp_path / "shadowed"
    marker_module(project / "argparse.py", marker, fail=True)

    with TestClient(create_app(project, allowed_hosts_extra=["testserver"])) as client:
        catalog = client.get("/api/nodes").json()
        assert catalog["errors"] == [] and catalog["definitions"] == []
        client.post("/api/workflows", json={"id": "empty", "name": "Empty"}, headers=HEADERS)
        run = client.post("/api/workflows/empty/runs", json={}, headers=HEADERS).json()
        assert wait_for(client, run["id"])["status"] == "SUCCEEDED"
    assert not marker.exists()


def test_cross_site_browser_requests_cannot_reach_the_api(tmp_path) -> None:
    project = tmp_path / "project"
    Workspace.init(project, node_modules=["planted"])
    marker = tmp_path / "imported"
    marker_module(project / "planted.py", marker)

    with TestClient(create_app(project, allowed_hosts_extra=["testserver"])) as client:
        for site in ("cross-site", "same-site"):
            response = client.get("/api/nodes", headers={"Sec-Fetch-Site": site})
            assert response.status_code == 403, site
            assert client.post("/api/workflows", json={"id": "x", "name": "x"},
                               headers={**HEADERS, "Sec-Fetch-Site": site}).status_code == 403
        assert not marker.exists()

        assert client.get("/api/health", headers={"Sec-Fetch-Site": "same-origin"}).status_code \
            == 200
        assert client.get("/api/health", headers={"Sec-Fetch-Site": "none"}).status_code == 200
        assert client.get("/api/health").status_code == 200
        assert client.get("/", headers={"Sec-Fetch-Site": "cross-site"}).status_code != 403


# ---------------------------------------------------------------------- project trust

ANSWER_WORKFLOW = json.dumps({
    "schema_version": 1, "id": "answer", "name": "Answer", "edges": [],
    "nodes": [{"id": "answer", "type": "planted:answer", "params": {},
               "position": {"x": 0, "y": 0}}],
})


@pytest.fixture
def received(tmp_path):
    """A project made elsewhere and copied here: its node module records being imported."""
    origin = tmp_path / "origin"
    Workspace.init(origin, node_modules=["planted"]).save_workflow(load_workflow(ANSWER_WORKFLOW))
    marker = tmp_path / "imported"
    (origin / "planted.py").write_text(
        f"import pathlib\npathlib.Path({str(marker)!r}).write_text('imported')\n"
        "from neuroweave import node\n\n\n@node\ndef answer() -> int:\n    return 42\n",
        encoding="utf-8")
    project = tmp_path / "received"
    shutil.copytree(origin, project)
    revoke_project(origin)
    sys.modules.pop("planted", None)
    yield project, marker
    sys.modules.pop("planted", None)
    for root in (str(origin.resolve()), str(project.resolve())):
        while root in sys.path:
            sys.path.remove(root)


def nw(project: Path, *args: str):
    return CliRunner().invoke(app, ["--project", str(project), *args])


def test_projects_created_here_are_trusted_and_received_ones_are_not(tmp_path, received) -> None:
    project, _ = received
    assert is_trusted(Workspace.init(tmp_path / "mine").root)
    assert not is_trusted(project)

    result = nw(project, "init")
    assert result.exit_code == 0
    assert "not trusted yet" in result.output and not is_trusted(project)


def test_cli_refuses_to_import_code_from_an_untrusted_project(received) -> None:
    project, marker = received
    for command in (["nodes"], ["validate", "answer"], ["run", "answer"]):
        result = nw(project, *command)
        assert result.exit_code == 1, command
        assert "is not trusted" in result.output and "nw --project" in result.output
    for command in (["workflows", "list"], ["runs"],
                    ["workflows", "import", "--force", str(project / ".neuroweave" / "workflows"
                                                           / "answer.json")]):
        assert nw(project, *command).exit_code == 0, command
    assert not marker.exists()

    assert nw(project, "trust").exit_code == 0
    result = nw(project, "run", "answer")
    assert result.exit_code == 0, result.output
    assert marker.exists()

    assert nw(project, "trust", "--revoke").exit_code == 0
    assert nw(project, "nodes").exit_code == 1


def test_interactive_cli_asks_once_before_trusting(received, monkeypatch) -> None:
    project, marker = received
    monkeypatch.setattr("neuroweave.cli._interactive", lambda: True)

    result = CliRunner().invoke(app, ["--project", str(project), "nodes"], input="n\n")
    assert result.exit_code == 1 and "Do you trust this project's code?" in result.output
    assert not marker.exists() and not is_trusted(project)

    result = CliRunner().invoke(app, ["--project", str(project), "nodes"], input="y\n")
    assert result.exit_code == 0, result.output
    assert "planted:answer" in result.output and marker.exists() and is_trusted(project)
    assert "Do you trust" not in nw(project, "nodes").output


def test_studio_api_imports_nothing_until_the_project_is_trusted(received) -> None:
    project, marker = received
    with TestClient(create_app(project, allowed_hosts_extra=["testserver"])) as client:
        catalog = client.get("/api/nodes").json()
        assert catalog["definitions"] == []
        assert "is not trusted" in catalog["errors"][0]["error"]
        response = client.post("/api/workflows/answer/runs", json={}, headers=HEADERS)
        assert response.status_code == 403 and "nw --project" in response.json()["detail"]
        assert client.get("/api/workflows").status_code == 200
        assert client.get("/api/runs").json() == []
        assert not marker.exists()

        trust_project(project)
        assert [d["id"] for d in client.get("/api/nodes").json()["definitions"]] == [
            "planted:answer"]
        run = client.post("/api/workflows/answer/runs", json={}, headers=HEADERS).json()
        assert wait_for(client, run["id"])["status"] == "SUCCEEDED"
    assert marker.exists()


def test_projects_without_node_modules_need_no_trust(tmp_path) -> None:
    project = tmp_path / "plain"
    Workspace.init(project)
    revoke_project(project)
    assert nw(project, "nodes").exit_code == 0
    with TestClient(create_app(project, allowed_hosts_extra=["testserver"])) as client:
        assert client.get("/api/nodes").json()["errors"] == []


def test_cli_logs_never_reads_outside_the_workspace(tmp_path, demo_project) -> None:
    result = nw(demo_project.root, "run", "rainfall-yield")
    assert result.exit_code == 0, result.output
    run = demo_project.db.list_runs(limit=1)[0]
    execution = next(e for e in demo_project.db.node_executions(run.id) if e.node_id == "load")
    assert nw(demo_project.root, "logs", run.id, "load").exit_code == 0

    secret = tmp_path / "secret.txt"
    secret.write_text("not for the terminal", encoding="utf-8")
    demo_project.db.update_node_execution(execution.id, log_path="../../secret.txt")
    result = nw(demo_project.root, "logs", run.id, "load")
    assert result.exit_code == 1 and "outside the workspace" in result.output
    assert "not for the terminal" not in result.output


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_recording_git_state_does_not_run_commands_from_the_repository_config(tmp_path) -> None:
    repo = tmp_path / "repo"
    marker = tmp_path / "fsmonitor-ran"

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                        *args], check=True, capture_output=True)

    repo.mkdir()
    git("init", "-q")
    (repo / "file.txt").write_text("x", encoding="utf-8")
    git("add", "file.txt")
    git("commit", "-q", "-m", "init")
    git("config", "core.fsmonitor", f"touch {shlex.quote(str(marker))}; false")

    info = git_info(repo)
    assert info is not None and len(info["commit"]) == 40
    assert not marker.exists()


def test_unreadable_trust_file_trusts_nothing(tmp_path, trust_file) -> None:
    project = Workspace.init(tmp_path / "mine").root
    trust_file.write_text("{not json", encoding="utf-8")
    assert not is_trusted(project)
    trust_project(project)
    assert is_trusted(project)
