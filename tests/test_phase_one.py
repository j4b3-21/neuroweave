from __future__ import annotations

import json
import os
from pathlib import Path

from typer.testing import CliRunner

from neuroweave.cli import app
from neuroweave.store.workspace import Workspace, initialize_workspace

runner = CliRunner()


def test_initialize_workspace_creates_structure(tmp_path: Path) -> None:
    result = initialize_workspace(tmp_path)
    workspace_path = tmp_path.resolve() / ".neuroweave"

    assert result.workspace_path == workspace_path
    assert (workspace_path / "project.json").is_file()
    for directory in ("workflows", "snapshots", "runs", "artifacts"):
        assert (workspace_path / directory).is_dir()
    config = json.loads((workspace_path / "project.json").read_text())
    assert config["schema_version"] == 2
    assert config["name"] == tmp_path.name
    assert config["node_modules"] == []


def test_initialize_workspace_preserves_existing_files(tmp_path: Path) -> None:
    workspace_path = tmp_path / ".neuroweave"
    workspace_path.mkdir()
    project_file = workspace_path / "project.json"
    project_file.write_text('{"custom": true}\n', encoding="utf-8")
    graph_file = workspace_path / "graph.json"
    graph_file.write_text('{"graph": "custom"}\n', encoding="utf-8")

    result = initialize_workspace(tmp_path)

    assert project_file.read_text(encoding="utf-8") == '{"custom": true}\n'
    assert graph_file.read_text(encoding="utf-8") == '{"graph": "custom"}\n'
    assert project_file.resolve() in result.existing_files
    # Opening a v1 workspace fills defaults in memory without rewriting the file.
    config = Workspace(tmp_path).config
    assert config.name == tmp_path.name and config.node_modules == []
    assert project_file.read_text(encoding="utf-8") == '{"custom": true}\n'


def test_initialize_is_idempotent(tmp_path: Path) -> None:
    initialize_workspace(tmp_path)
    second = initialize_workspace(tmp_path)
    assert not second.created_files and not second.created_directories


def test_nw_init_command_outputs_summary(tmp_path: Path) -> None:
    previous = Path.cwd()
    os.chdir(tmp_path)
    try:
        result = runner.invoke(app, ["init", "--node-module", "my_nodes"])
    finally:
        os.chdir(previous)
    assert result.exit_code == 0, result.output
    assert "Initialized workspace at" in result.output
    config = json.loads((tmp_path / ".neuroweave" / "project.json").read_text())
    assert config["node_modules"] == ["my_nodes"]
