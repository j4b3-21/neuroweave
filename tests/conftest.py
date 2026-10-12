from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from neuroweave.kernel.serialization import load_workflow
from neuroweave.sdk.registry import NodeRegistry, default_registry, load_node_modules
from neuroweave.store.trust import TRUST_FILE_ENV
from neuroweave.store.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "examples" / "research_demo"


@pytest.fixture(autouse=True)
def trust_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep project trust decisions out of the developer's real configuration."""
    path = tmp_path / "trusted-projects.json"
    monkeypatch.setenv(TRUST_FILE_ENV, str(path))
    return path


@pytest.fixture
def registry() -> NodeRegistry:
    return NodeRegistry()


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace.init(tmp_path / "project")


@pytest.fixture
def demo_project(tmp_path: Path):
    """A fresh copy of the research example, initialised as a NeuroWeave project."""
    project = tmp_path / "demo"
    shutil.copytree(DEMO_DIR, project,
                    ignore=shutil.ignore_patterns(".neuroweave", "__pycache__"))
    ws = Workspace.init(project, node_modules=["demo_nodes"])
    ws.save_workflow(load_workflow((project / "workflow.json").read_text(encoding="utf-8")))
    sys.modules.pop("demo_nodes", None)
    yield ws
    sys.modules.pop("demo_nodes", None)
    with_root = str(project.resolve())
    while with_root in sys.path:
        sys.path.remove(with_root)


@pytest.fixture
def demo_registry(demo_project: Workspace) -> NodeRegistry:
    errors = load_node_modules(["demo_nodes"], demo_project.root)
    assert not errors, errors
    return default_registry
