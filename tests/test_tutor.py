"""nw tutor materialises a sample project and runs real commands (no network, no Studio)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from neuroweave.cli import app
from neuroweave.onboarding import ONBOARDING_FILE_ENV
from neuroweave.store.workspace import Workspace
from neuroweave.tutorial.walkthrough import (
    TutorialError,
    materialize_tutorial_project,
    run_chapters,
)

runner = CliRunner()


def test_materialize_sets_tutorial_flag_and_imports_workflow(tmp_path: Path):
    ws = materialize_tutorial_project(tmp_path / "tutor")
    assert ws.config.tutorial is True
    assert ws.config.node_modules == ["demo_nodes"]
    assert (ws.root / "demo_nodes.py").is_file()
    assert (ws.root / "data" / "field_trial.csv").is_file()
    assert ws.load_workflow("rainfall-yield").id == "rainfall-yield"


def test_reset_refuses_non_tutorial_folder(tmp_path: Path):
    foreign = tmp_path / "mine"
    Workspace.init(foreign, name="Mine", node_modules=["demo_nodes"])
    with pytest.raises(TutorialError, match="not marked as a tutorial"):
        materialize_tutorial_project(foreign, reset=True)


def test_tutor_chapters_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(ONBOARDING_FILE_ENV, str(tmp_path / "onboarding.json"))
    ws = materialize_tutorial_project(tmp_path / "tutor")
    ids = run_chapters(ws.root, yes=True)
    assert "first" in ids and "changed" in ids
    runs = ws.db.list_runs()
    assert len(runs) >= 3
    # Incremental: the changed run should have reused some nodes and re-executed others.
    changed = ws.db.get_run(ids["changed"])
    assert changed is not None and changed.status == "SUCCEEDED"
    executions = {e.node_id: e for e in ws.db.node_executions(changed.id)}
    assert executions["bootstrap"].cache_hit is False
    assert executions["report"].cache_hit is False
    assert executions["load"].cache_hit is True
    # A reproduction run exists and succeeded.
    reproductions = [r for r in runs if r.reproduces_run_id]
    assert reproductions and reproductions[0].status == "SUCCEEDED"


def test_cli_tutor_no_studio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(ONBOARDING_FILE_ENV, str(tmp_path / "onboarding.json"))
    target = tmp_path / "cli-tutor"
    result = runner.invoke(app, ["tutor", "--dir", str(target), "--yes", "--no-studio"])
    assert result.exit_code == 0, result.output
    assert "Tutorial project ready" in result.output
    assert "Cheat sheet" in result.output
    assert Workspace(target).config.tutorial is True
