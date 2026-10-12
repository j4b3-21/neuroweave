"""Isolated environment rebuild planning and reuse (no network)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from neuroweave.runtime.environment import capture_environment
from neuroweave.runtime.executor import run_workflow
from neuroweave.runtime.isolated import (
    IsolatedReproductionError,
    build_environment,
    env_dir_for,
    find_uv,
    plan_environment,
    prepare_isolated_reproduction,
    worker_command,
)
from neuroweave.store.trust import revoke_project
from neuroweave.store.workspace import Workspace


def test_plan_builds_uv_commands_with_no_deps_and_no_build(demo_project: Workspace, demo_registry):
    run = run_workflow(demo_project, demo_project.load_workflow("rainfall-yield"), demo_registry)
    plan = plan_environment(demo_project, run.environment, uv="/usr/bin/uv")
    assert plan.lock_hash == run.environment["lock"]["hash"]
    assert plan.commands[0][:3] == ["/usr/bin/uv", "venv", "--python"]
    assert plan.python_version == run.environment["python"]["version"]
    install = plan.commands[1]
    assert install[:6] == [
        "/usr/bin/uv", "pip", "install", "--python",
        str(plan.env_dir / "bin/python"), "--no-deps",
    ]
    assert "--no-build" in install
    assert install[-2:] == ["-r", str(plan.lock_path)]
    nw = plan.commands[2]
    assert nw[0:4] == ["/usr/bin/uv", "pip", "install", "--python"]
    assert str(plan.neuroweave_source) in nw


def test_plan_allow_build_omits_no_build(demo_project: Workspace, demo_registry):
    run = run_workflow(demo_project, demo_project.load_workflow("rainfall-yield"), demo_registry)
    plan = plan_environment(demo_project, run.environment, allow_build=True, uv="uv")
    assert "--no-build" not in plan.commands[1]


def test_build_reuses_marker_and_rebuild_forces(demo_project: Workspace, demo_registry, tmp_path):
    run = run_workflow(demo_project, demo_project.load_workflow("rainfall-yield"), demo_registry)
    calls: list[list[str]] = []

    def fake(command, cwd):
        calls.append(list(command))
        # Simulate `uv venv` creating the interpreter path the plan expects.
        env_dir = Path(command[-1]) if command[1] == "venv" else None
        if env_dir is not None:
            (env_dir / "bin").mkdir(parents=True, exist_ok=True)
            (env_dir / "bin" / "python").write_text("#!/bin/true\n", encoding="utf-8")
            (env_dir / "bin" / "python").chmod(0o755)
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    first = build_environment(demo_project, run.environment, runner=fake, uv="uv")
    assert first == env_dir_for(demo_project, run.environment["lock"]["hash"])
    recorded = (first / ".complete").read_text(encoding="utf-8").strip()
    assert recorded == run.environment["lock"]["hash"]
    assert (first / "requirements.lock").is_file()
    n_first = len(calls)

    second = build_environment(demo_project, run.environment, runner=fake, uv="uv")
    assert second == first
    assert len(calls) == n_first  # reused; no new commands

    build_environment(demo_project, run.environment, runner=fake, uv="uv", rebuild=True)
    assert len(calls) == 2 * n_first


def test_missing_uv_raises(monkeypatch):
    monkeypatch.setattr("neuroweave.runtime.isolated.shutil.which", lambda _name: None)
    with pytest.raises(IsolatedReproductionError, match="uv"):
        find_uv()


def test_missing_lock_raises(demo_project: Workspace):
    env = capture_environment(demo_project.root)  # no artifacts -> no lock
    with pytest.raises(IsolatedReproductionError, match="no environment lock"):
        plan_environment(demo_project, env, uv="uv")


def test_untrusted_project_raises(demo_project: Workspace, demo_registry):
    run = run_workflow(demo_project, demo_project.load_workflow("rainfall-yield"), demo_registry)
    revoke_project(demo_project.root)
    with pytest.raises(Exception, match="not trusted"):
        plan_environment(demo_project, run.environment, uv="uv")


def test_missing_local_path_raises(demo_project: Workspace, demo_registry, tmp_path):
    run = run_workflow(demo_project, demo_project.load_workflow("rainfall-yield"), demo_registry)
    gone = tmp_path / "missing-pkg"
    lock_text = f"mypkg @ {gone.as_uri()}\n"
    digest, _ = demo_project.artifacts.put_bytes(lock_text.encode("utf-8"))
    environment = dict(run.environment)
    environment["lock"] = {
        "format": "requirements",
        "hash": digest,
        "local": ["mypkg"],
        "neuroweave": run.environment["lock"]["neuroweave"],
    }
    with pytest.raises(IsolatedReproductionError, match="no longer at their recorded paths"):
        plan_environment(demo_project, environment, uv="uv")


def test_prepare_isolated_reproduction_sets_trigger(demo_project: Workspace, demo_registry):
    run = run_workflow(demo_project, demo_project.load_workflow("rainfall-yield"), demo_registry)
    original, pending = prepare_isolated_reproduction(demo_project, run.id)
    assert original.id == run.id
    assert pending.trigger == "reproduce-isolated"
    assert pending.reproduces_run_id == run.id
    assert pending.use_cache is False
    assert pending.seed == run.seed
    command = worker_command(env_dir_for(demo_project, run.environment["lock"]["hash"]),
                             demo_project, pending.id)
    assert command[1:4] == ["-P", "-m", "neuroweave.runtime.worker"]
    assert "--run-id" in command and pending.id in command
