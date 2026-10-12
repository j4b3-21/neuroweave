"""Pinned environment locks and project lockfile capture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from neuroweave.runtime.environment import (
    EnvironmentLock,
    capture_environment,
    environment_lock,
    project_lockfiles,
)
from neuroweave.runtime.executor import run_workflow
from neuroweave.store.artifacts import ArtifactStore
from neuroweave.store.workspace import Workspace


class _FakeDist:
    """Minimal stand-in for ``importlib.metadata.Distribution``."""

    def __init__(self, name: str, version: str, direct_url: dict[str, Any] | None = None):
        self.metadata = {"Name": name}
        self.version = version
        self._direct_url = direct_url

    def read_text(self, filename: str) -> str | None:
        if filename == "direct_url.json" and self._direct_url is not None:
            return json.dumps(self._direct_url)
        return None


def test_lock_classifies_index_vcs_and_local_installs(tmp_path: Path):
    local = tmp_path / "mypkg"
    local.mkdir()
    dists = [
        _FakeDist("Zebra", "1.0.0"),
        _FakeDist("Alpha", "2.3.4"),
        _FakeDist(
            "VcsPkg", "0.1.0",
            {"url": "https://github.com/ex/vcs.git",
             "vcs_info": {"vcs": "git", "commit_id": "abc123"}},
        ),
        _FakeDist(
            "LocalPkg", "0.2.0",
            {"url": local.as_uri(), "dir_info": {"editable": True}},
        ),
        _FakeDist(
            "neuroweave", "0.2.0",
            {"url": (tmp_path / "nw").as_uri(), "dir_info": {"editable": True}},
        ),
    ]
    lock = environment_lock(dists)  # type: ignore[arg-type]
    assert isinstance(lock, EnvironmentLock)
    lines = [line for line in lock.text.splitlines() if line]
    assert lines == [
        "Alpha==2.3.4",
        f"LocalPkg @ {local.resolve().as_uri()}",
        "VcsPkg @ git+https://github.com/ex/vcs.git@abc123",
        "Zebra==1.0.0",
    ]
    assert lock.local == ["localpkg"]
    assert lock.neuroweave["version"] == "0.2.0"
    pinned_names = {line.split("=", 1)[0].split(" ", 1)[0].lower() for line in lines}
    assert "neuroweave" not in pinned_names


def test_lock_text_is_deterministic_and_hash_stable():
    dists = [
        _FakeDist("B", "1"),
        _FakeDist("A", "2"),
    ]
    first = environment_lock(dists)  # type: ignore[arg-type]
    second = environment_lock(list(reversed(dists)))  # type: ignore[arg-type]
    assert first.text == second.text == "A==2\nB==1\n"
    assert first.hash == second.hash == hashlib.sha256(first.text.encode()).hexdigest()


def test_project_lockfiles_detects_recognised_files(tmp_path: Path):
    (tmp_path / "uv.lock").write_text("a = 1\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("x==1\n", encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text("y==2\n", encoding="utf-8")
    (tmp_path / "poetry.lock").write_text("[[package]]\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore me\n", encoding="utf-8")
    found = project_lockfiles(tmp_path)
    names = [name for name, _ in found]
    assert names == ["uv.lock", "poetry.lock", "requirements-dev.txt", "requirements.txt"]
    assert found[0][1] == b"a = 1\n"


def test_capture_stores_lock_and_project_lockfiles(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    store = ArtifactStore(tmp_path / "artifacts")
    env = capture_environment(project, store)
    assert "packages" in env and env["packages"]
    lock = env["lock"]
    assert lock["format"] == "requirements"
    assert store.verify(lock["hash"])
    text = store.get_bytes(lock["hash"]).decode("utf-8")
    assert "typer==" in text or "typer @" in text or "pydantic" in text
    assert lock["neuroweave"]["version"]
    assert env["project_lockfiles"] == [
        {"path": "uv.lock", "hash": hashlib.sha256(b"version = 1\n").hexdigest()},
    ]
    assert store.verify(env["project_lockfiles"][0]["hash"])


def test_capture_without_artifacts_omits_lock(tmp_path: Path):
    env = capture_environment(tmp_path)
    assert "lock" not in env
    assert "project_lockfiles" not in env
    assert "packages" in env


def test_run_records_lock_hash(demo_project: Workspace, demo_registry):
    workflow = demo_project.load_workflow("rainfall-yield")
    run = run_workflow(demo_project, workflow, demo_registry, seed=1)
    assert run.environment is not None
    lock = run.environment["lock"]
    assert demo_project.artifacts.verify(lock["hash"])
    # A second run in the same interpreter produces the same lock hash.
    again = run_workflow(demo_project, workflow, demo_registry, seed=1)
    assert again.environment["lock"]["hash"] == lock["hash"]
