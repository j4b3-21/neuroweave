from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path


WORKSPACE_DIRECTORY = ".neuroweave"
PROJECT_FILE = "project.json"
GRAPH_FILE = "graph.json"
WORKSPACE_SUBDIRECTORIES = ("snapshots", "runs", "artifacts")


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
                "Created directories: "
                + ", ".join(str(path) for path in self.created_directories)
            )

        if self.created_files:
            lines.append(
                "Created files: "
                + ", ".join(str(path) for path in self.created_files)
            )

        if self.existing_directories or self.existing_files:
            existing_items = [
                *[str(path) for path in self.existing_directories],
                *[str(path) for path in self.existing_files],
            ]
            lines.append("Preserved existing items: " + ", ".join(existing_items))

        return lines


def initialize_workspace(base_path: Path) -> InitializationResult:
    project_root = base_path.resolve()
    workspace_path = project_root / WORKSPACE_DIRECTORY

    created_directories: list[Path] = []
    existing_directories: list[Path] = []
    created_files: list[Path] = []
    existing_files: list[Path] = []

    workspace_path.mkdir(parents=True, exist_ok=True)

    for relative_directory in WORKSPACE_SUBDIRECTORIES:
        directory_path = workspace_path / relative_directory
        if directory_path.exists():
            existing_directories.append(directory_path)
            continue

        directory_path.mkdir(parents=True, exist_ok=True)
        created_directories.append(directory_path)

    project_file = workspace_path / PROJECT_FILE
    if project_file.exists():
        existing_files.append(project_file)
    else:
        project_file.write_text(
            json.dumps(
                _project_payload(project_root=project_root),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        created_files.append(project_file)

    graph_file = workspace_path / GRAPH_FILE
    if graph_file.exists():
        existing_files.append(graph_file)
    else:
        graph_file.write_text(
            json.dumps(
                _graph_payload(),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        created_files.append(graph_file)

    return InitializationResult(
        workspace_path=workspace_path,
        created_directories=tuple(created_directories),
        created_files=tuple(created_files),
        existing_directories=tuple(existing_directories),
        existing_files=tuple(existing_files),
    )


def _project_payload(*, project_root: Path) -> dict[str, str | int]:
    timestamp = datetime.now(UTC).isoformat()

    return {
        "schema_version": 1,
        "name": project_root.name,
        "project_root": str(project_root),
        "workspace": WORKSPACE_DIRECTORY,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def _graph_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "nodes": [],
        "edges": [],
    }
