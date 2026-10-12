"""Server-side services: node catalogue discovery and run process management.

Neither service imports project code into the server process. The catalogue is discovered
by ``neuroweave.runtime.catalog`` and runs execute in ``neuroweave.runtime.worker``, and
neither process is started for a project the user has not trusted (``neuroweave.store.trust``).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

from pydantic import BaseModel, Field

from neuroweave.kernel.definitions import NodeDefinition
from neuroweave.kernel.model import Workflow
from neuroweave.runtime.executor import prepare_run
from neuroweave.sdk.registry import ModuleLoadError
from neuroweave.store.db import RunRecord
from neuroweave.store.files import utc_now
from neuroweave.store.trust import UntrustedProjectError, needs_trust, require_trusted
from neuroweave.store.workspace import Workspace

CANCEL_GRACE_SECONDS = 10.0
# `python -m` runs with the project directory as cwd and would put it first on sys.path, so a
# project file named like a standard-library module (argparse.py, json.py) would be imported
# before any NeuroWeave code runs. -P (Python 3.11+) leaves it off; node modules are still
# imported from the project root, which load_node_modules adds explicitly.
SAFE_PATH = ("-P",)


class Catalog(BaseModel):
    definitions: list[NodeDefinition] = Field(default_factory=list)
    errors: list[ModuleLoadError] = Field(default_factory=list)
    loaded_at: str | None = None

    def by_id(self) -> dict[str, NodeDefinition]:
        return {d.id: d for d in self.definitions}


class CatalogService:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self._lock = threading.Lock()
        self._signature: tuple | None = None
        self._catalog: Catalog | None = None

    def _signature_now(self) -> tuple:
        """Modification times of the project's node module files and project.json."""
        config = self.workspace.config
        stamps: list[tuple[str, float]] = []
        project = self.workspace.project_file
        if project.exists():
            stamps.append((str(project), project.stat().st_mtime))
        for module in config.node_modules:
            base = self.workspace.root.joinpath(*module.split("."))
            candidates = [base.with_suffix(".py")]
            if base.is_dir():
                candidates += sorted(base.rglob("*.py"))
            for path in candidates:
                if path.is_file():
                    stamps.append((str(path), path.stat().st_mtime))
        trusted = not needs_trust(self.workspace.root, config.node_modules)
        return (tuple(config.node_modules), tuple(stamps), trusted)

    def get(self, *, refresh: bool = False) -> Catalog:
        with self._lock:
            signature = self._signature_now()
            if refresh or self._catalog is None or signature != self._signature:
                self._catalog = self._discover()
                self._signature = signature
            return self._catalog

    def _discover(self) -> Catalog:
        try:
            require_trusted(self.workspace.root, self.workspace.config.node_modules)
        except UntrustedProjectError as exc:
            return Catalog(errors=[ModuleLoadError(module="*", error=str(exc), traceback="")],
                           loaded_at=utc_now())
        try:
            completed = subprocess.run(
                [sys.executable, *SAFE_PATH, "-m", "neuroweave.runtime.catalog", "--workspace",
                 str(self.workspace.root)],
                capture_output=True, text=True, timeout=120, cwd=self.workspace.root,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return Catalog(errors=[ModuleLoadError(module="*", error="Catalogue discovery timed "
                                                   "out after 120 s.", traceback="")],
                           loaded_at=utc_now())
        if completed.returncode != 0:
            return Catalog(errors=[ModuleLoadError(module="*", error="Catalogue discovery "
                                                   "failed.", traceback=completed.stderr[-4000:])],
                           loaded_at=utc_now())
        data = json.loads(completed.stdout)
        return Catalog(definitions=data["definitions"], errors=data["errors"],
                       loaded_at=utc_now())


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class RunManager:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self._processes: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    def start(
        self, workflow: Workflow, *, seed: int | None, use_cache: bool, trigger: str = "studio",
        reproduces_run_id: str | None = None,
    ) -> RunRecord:
        require_trusted(self.workspace.root, self.workspace.config.node_modules)
        db = self.workspace.db
        run = prepare_run(self.workspace, workflow, seed=seed, use_cache=use_cache,
                          trigger=trigger, reproduces_run_id=reproduces_run_id)
        run_dir = self.workspace.run_dir(run.id)
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(run_dir / "worker.log", "ab") as log:
                process = subprocess.Popen(
                    [sys.executable, *SAFE_PATH, "-m", "neuroweave.runtime.worker", "--workspace",
                     str(self.workspace.root), "--run-id", run.id],
                    cwd=self.workspace.root, stdout=log, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, start_new_session=True,
                )
        except OSError as exc:
            db.update_run(run.id, status="FAILED", finished_at=utc_now(),
                          error=f"Could not start worker process: {exc}")
        else:
            with self._lock:
                self._processes[run.id] = process
            db.update_run(run.id, worker_pid=process.pid)
        record = db.get_run(run.id)
        assert record is not None
        return record

    def poll(self) -> None:
        """Reap finished workers and close out runs whose worker died."""
        with self._lock:
            for run_id, process in list(self._processes.items()):
                if process.poll() is not None:
                    del self._processes[run_id]
        self.workspace.db.reconcile_stale_runs(pid_alive)

    def cancel(self, run_id: str) -> RunRecord | None:
        db = self.workspace.db
        run = db.get_run(run_id)
        if run is None or run.status not in ("PENDING", "RUNNING"):
            return run
        db.request_cancel(run_id)
        with self._lock:
            process = self._processes.get(run_id)
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGTERM)
            timer = threading.Timer(CANCEL_GRACE_SECONDS, self._kill_if_alive, args=(process,))
            timer.daemon = True
            timer.start()
        elif run.worker_pid and pid_alive(run.worker_pid):
            os.kill(run.worker_pid, signal.SIGTERM)
        return db.get_run(run_id)

    @staticmethod
    def _kill_if_alive(process: subprocess.Popen) -> None:
        if process.poll() is None:
            process.kill()
            process.wait()

    def shutdown(self) -> None:
        with self._lock:
            processes = list(self._processes.values())
        for process in processes:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)


def tail(path: Path, max_bytes: int = 1_000_000) -> str:
    if not path.exists():
        return ""
    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes))
        data = handle.read()
    prefix = "[… earlier output truncated …]\n" if size > max_bytes else ""
    return prefix + data.decode("utf-8", errors="replace")
