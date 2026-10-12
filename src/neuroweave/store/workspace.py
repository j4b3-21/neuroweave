"""The local project workspace (``.neuroweave/``).

Layout::

    .neuroweave/
    ├── project.json        project configuration (authoritative)
    ├── workflows/<id>.json current, editable workflow definitions (authoritative)
    ├── snapshots/<hash>.json immutable, content-addressed workflow snapshots
    ├── runs/<run_id>/      per-run log files
    ├── artifacts/objects/  content-addressed artifact bytes
    └── neuroweave.db       SQLite: runs, node executions, artifacts, provenance, metrics
                            (authoritative for execution history)

``graph.json`` from schema version 1 is never modified; if it contains nodes it is imported
once as the workflow ``main``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from neuroweave.kernel.model import WORKFLOW_ID_PATTERN, Workflow
from neuroweave.kernel.serialization import dump_workflow, load_workflow, pretty_json, snapshot_hash
from neuroweave.store.files import (
    RUN_ID_PATTERN,
    SHA256_PATTERN,
    atomic_write_text,
    utc_now,
)
from neuroweave.store.trust import trust_project

WORKSPACE_DIRECTORY = ".neuroweave"
PROJECT_FILE = "project.json"
LEGACY_GRAPH_FILE = "graph.json"
DATABASE_FILE = "neuroweave.db"
WORKSPACE_SUBDIRECTORIES = ("workflows", "snapshots", "runs", "artifacts")
PROJECT_SCHEMA_VERSION = 2

_WORKFLOW_ID = re.compile(WORKFLOW_ID_PATTERN)


class WorkspaceNotFoundError(FileNotFoundError):
    pass


class WorkflowNotFoundError(KeyError):
    pass


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: int = PROJECT_SCHEMA_VERSION
    name: str = ""
    workspace: str = WORKSPACE_DIRECTORY
    created_at: str | None = None
    updated_at: str | None = None
    node_modules: list[str] = Field(
        default_factory=list,
        description="Python modules/packages (importable from the project root) whose @node "
        "functions form the project's node catalogue.",
    )
    default_seed: int = 0
    max_input_snapshot_bytes: int = Field(
        default=50 * 1024 * 1024,
        description="External input files up to this size are copied into the artifact store; "
        "larger files are recorded by hash only.",
    )
    tutorial: bool = Field(
        default=False,
        description="True when this project was created by `nw tutor`. The Studio uses it to "
        "enable demo-specific tour steps.",
    )


@dataclass(frozen=True, slots=True)
class InitializationResult:
    workspace_path: Path
    created_directories: tuple[Path, ...]
    created_files: tuple[Path, ...]
    existing_directories: tuple[Path, ...]
    existing_files: tuple[Path, ...]

    def summary_lines(self) -> list[str]:
        lines = [f"Initialized workspace at {self.workspace_path}"]
        if self.created_directories:
            lines.append(
                "Created directories: " + ", ".join(str(p) for p in self.created_directories)
            )
        if self.created_files:
            lines.append("Created files: " + ", ".join(str(p) for p in self.created_files))
        if self.existing_directories or self.existing_files:
            existing = [str(p) for p in (*self.existing_directories, *self.existing_files)]
            lines.append("Preserved existing items: " + ", ".join(existing))
        return lines


def initialize_workspace(
    base_path: Path, *, name: str | None = None, node_modules: list[str] | None = None
) -> InitializationResult:
    """Create the workspace layout. Idempotent: existing files and directories are preserved.

    Creating ``project.json`` also trusts the project (see :mod:`neuroweave.store.trust`): the
    user is setting it up here. An existing ``project.json`` may have come from elsewhere, so
    it is never trusted implicitly."""
    project_root = base_path.resolve()
    workspace_path = project_root / WORKSPACE_DIRECTORY
    created_directories: list[Path] = []
    existing_directories: list[Path] = []
    created_files: list[Path] = []
    existing_files: list[Path] = []

    workspace_path.mkdir(parents=True, exist_ok=True)
    for relative in WORKSPACE_SUBDIRECTORIES:
        directory = workspace_path / relative
        if directory.exists():
            existing_directories.append(directory)
        else:
            directory.mkdir(parents=True)
            created_directories.append(directory)

    project_file = workspace_path / PROJECT_FILE
    if project_file.exists():
        existing_files.append(project_file)
    else:
        timestamp = utc_now()
        config = ProjectConfig(
            name=name or project_root.name,
            created_at=timestamp,
            updated_at=timestamp,
            node_modules=node_modules or [],
        )
        atomic_write_text(project_file, pretty_json(config.model_dump(mode="json")))
        created_files.append(project_file)
        trust_project(project_root)

    return InitializationResult(
        workspace_path=workspace_path,
        created_directories=tuple(created_directories),
        created_files=tuple(created_files),
        existing_directories=tuple(existing_directories),
        existing_files=tuple(existing_files),
    )


class Workspace:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.dir = self.root / WORKSPACE_DIRECTORY
        if not self.dir.is_dir():
            raise WorkspaceNotFoundError(
                f"No NeuroWeave workspace at {self.root}. Run `nw init` in the project directory."
            )
        for relative in WORKSPACE_SUBDIRECTORIES:
            (self.dir / relative).mkdir(exist_ok=True)
        self._import_legacy_graph()

    # ------------------------------------------------------------------ discovery

    @classmethod
    def open(cls, path: str | Path | None = None) -> Workspace:
        """Open the workspace at ``path`` or the nearest ancestor containing ``.neuroweave/``."""
        start = Path(path or Path.cwd()).resolve()
        for candidate in (start, *start.parents):
            if (candidate / WORKSPACE_DIRECTORY).is_dir():
                return cls(candidate)
        raise WorkspaceNotFoundError(
            f"No NeuroWeave workspace found in {start} or its parents. Run `nw init` first."
        )

    @classmethod
    def init(cls, path: str | Path, **kwargs) -> Workspace:
        initialize_workspace(Path(path), **kwargs)
        return cls(path)

    # ------------------------------------------------------------------ configuration

    @property
    def project_file(self) -> Path:
        return self.dir / PROJECT_FILE

    @property
    def config(self) -> ProjectConfig:
        data: dict = {}
        if self.project_file.exists():
            try:
                loaded = json.loads(self.project_file.read_text(encoding="utf-8"))
                data = loaded if isinstance(loaded, dict) else {}
            except json.JSONDecodeError as exc:
                raise ValueError(f"{self.project_file} is not valid JSON: {exc}") from exc
        config = ProjectConfig.model_validate(data)
        if not config.name:
            config.name = self.root.name
        return config

    def save_config(self, config: ProjectConfig) -> None:
        config.updated_at = utc_now()
        atomic_write_text(self.project_file, pretty_json(config.model_dump(mode="json")))

    # ------------------------------------------------------------------ workflows

    @property
    def workflows_dir(self) -> Path:
        return self.dir / "workflows"

    def _workflow_path(self, workflow_id: str) -> Path:
        if not _WORKFLOW_ID.match(workflow_id):
            raise ValueError(
                f"Invalid workflow id {workflow_id!r}: use lowercase letters, digits, '-' or '_'."
            )
        return self.workflows_dir / f"{workflow_id}.json"

    def list_workflows(self) -> list[Workflow]:
        workflows = []
        for path in sorted(self.workflows_dir.glob("*.json")):
            try:
                workflows.append(load_workflow(path.read_text(encoding="utf-8")))
            except (ValueError, ValidationError):
                continue
        return workflows

    def workflow_exists(self, workflow_id: str) -> bool:
        return self._workflow_path(workflow_id).exists()

    def load_workflow(self, workflow_id: str) -> Workflow:
        path = self._workflow_path(workflow_id)
        if not path.exists():
            raise WorkflowNotFoundError(f"Workflow '{workflow_id}' does not exist.")
        workflow = load_workflow(path.read_text(encoding="utf-8"))
        if workflow.id != workflow_id:
            raise ValueError(f"{path} declares id '{workflow.id}', expected '{workflow_id}'.")
        return workflow

    def save_workflow(self, workflow: Workflow) -> Path:
        path = self._workflow_path(workflow.id)
        atomic_write_text(path, dump_workflow(workflow))
        return path

    def delete_workflow(self, workflow_id: str) -> None:
        """Remove the editable definition. Snapshots and run history are kept."""
        path = self._workflow_path(workflow_id)
        if not path.exists():
            raise WorkflowNotFoundError(f"Workflow '{workflow_id}' does not exist.")
        path.unlink()

    # ------------------------------------------------------------------ snapshots

    @property
    def snapshots_dir(self) -> Path:
        return self.dir / "snapshots"

    def write_snapshot(self, workflow: Workflow) -> str:
        digest = snapshot_hash(workflow)
        path = self.snapshots_dir / f"{digest}.json"
        if not path.exists():
            atomic_write_text(path, dump_workflow(workflow))
        return digest

    def load_snapshot(self, digest: str) -> Workflow:
        if not SHA256_PATTERN.match(digest):
            raise ValueError(f"Invalid snapshot hash {digest!r}.")
        path = self.snapshots_dir / f"{digest}.json"
        if not path.exists():
            raise FileNotFoundError(f"Snapshot {digest} is missing from {self.snapshots_dir}.")
        workflow = load_workflow(path.read_text(encoding="utf-8"))
        if snapshot_hash(workflow) != digest:
            raise ValueError(f"Snapshot {digest} failed its integrity check.")
        return workflow

    # ------------------------------------------------------------------ runs / storage

    def run_dir(self, run_id: str) -> Path:
        if not RUN_ID_PATTERN.match(run_id):
            raise ValueError(f"Invalid run id {run_id!r}.")
        return self.dir / "runs" / run_id

    @cached_property
    def db(self):
        from neuroweave.store.db import Database

        return Database(self.dir / DATABASE_FILE)

    @cached_property
    def artifacts(self):
        from neuroweave.store.artifacts import ArtifactStore

        return ArtifactStore(self.dir / "artifacts")

    # ------------------------------------------------------------------ legacy

    def _import_legacy_graph(self) -> None:
        legacy = self.dir / LEGACY_GRAPH_FILE
        if not legacy.exists() or (self.workflows_dir / "main.json").exists():
            return
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not data.get("nodes"):
                return
            workflow = Workflow.model_validate(
                {"id": "main", "name": "main", "nodes": data["nodes"],
                 "edges": data.get("edges", [])}
            )
        except (ValueError, ValidationError):
            return
        self.save_workflow(workflow)
