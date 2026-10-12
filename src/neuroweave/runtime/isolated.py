"""Rebuild a run's recorded environment with ``uv`` and reproduce inside it.

This is process isolation into a fresh virtual environment pinned to the original run's
lock, not a security sandbox: node code still runs with the user's permissions. Building
needs network access to the package index unless every package is already cached by uv.
System libraries, CUDA and the OS itself are not rebuilt; the same OS and architecture
are required.

Commands are issued through an injectable ``CommandRunner`` so unit tests never touch
the network.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from neuroweave.runtime.environment import lock_text_from_environment
from neuroweave.runtime.executor import prepare_run
from neuroweave.store.trust import require_trusted
from neuroweave.store.workspace import Workspace

CommandRunner = Callable[[Sequence[str], Path | None], subprocess.CompletedProcess[str]]


class IsolatedReproductionError(RuntimeError):
    """A precondition failed or the rebuild refused to proceed."""


@dataclass
class BuildPlan:
    """The sequence of commands that would rebuild an environment from a lock."""

    env_dir: Path
    python_version: str
    lock_path: Path
    lock_hash: str
    neuroweave_source: Path
    allow_build: bool
    commands: list[list[str]] = field(default_factory=list)


def find_uv() -> str:
    path = shutil.which("uv")
    if not path:
        raise IsolatedReproductionError(
            "Isolated reproduction needs the `uv` tool on PATH "
            "(https://docs.astral.sh/uv/). Install it, then retry.")
    return path


def neuroweave_project_root() -> Path | None:
    """Locate the NeuroWeave source tree that contains ``pyproject.toml``, if any."""
    import neuroweave

    here = Path(neuroweave.__file__).resolve().parent
    for candidate in (here, *here.parents):
        pyproject = candidate / "pyproject.toml"
        if not pyproject.is_file():
            continue
        try:
            text = pyproject.read_text(encoding="utf-8")
        except OSError:
            continue
        if 'name = "neuroweave"' in text or "name = 'neuroweave'" in text:
            return candidate
    return None


def _file_url_path(url: str) -> Path | None:
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return None
    return Path(unquote(parsed.path))


def _local_paths_from_lock(lock_text: str, local_names: list[str]) -> dict[str, Path]:
    """Map lowercased package name -> local path for every ``name @ file://...`` line."""
    wanted = {name.lower() for name in local_names}
    found: dict[str, Path] = {}
    for line in lock_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or " @ " not in line:
            continue
        name, _, rest = line.partition(" @ ")
        path = _file_url_path(rest.strip())
        if path is None:
            continue
        key = name.strip().lower()
        if key in wanted or not wanted:
            found[key] = path
    return found


def _default_runner(command: Sequence[str], cwd: Path | None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command), cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, check=False,
    )


def env_dir_for(workspace: Workspace, lock_hash: str) -> Path:
    return workspace.dir / "envs" / lock_hash[:16]


def _recorded_python_version(environment: dict[str, Any]) -> str:
    python = environment.get("python") if isinstance(environment, dict) else None
    version = python.get("version") if isinstance(python, dict) else None
    if not isinstance(version, str) or not version:
        raise IsolatedReproductionError(
            "The original run did not record a Python version, so its environment "
            "cannot be rebuilt.")
    return version


def _resolve_neuroweave_source(lock_meta: dict[str, Any]) -> Path:
    source = lock_meta.get("source")
    if isinstance(source, str):
        path = _file_url_path(source)
        if path is not None and path.exists():
            # Editable installs point at the project root or a src layout parent.
            if (path / "pyproject.toml").is_file():
                return path
            if path.name == "src" and (path.parent / "pyproject.toml").is_file():
                return path.parent
            if path.is_dir():
                return path
    current = neuroweave_project_root()
    if current is not None:
        return current
    raise IsolatedReproductionError(
        "Cannot locate a NeuroWeave source tree to install into the rebuilt "
        "environment. Re-install NeuroWeave from a local checkout, or ensure the "
        "original source path still exists.")


def plan_environment(
    workspace: Workspace,
    environment: dict[str, Any],
    *,
    allow_build: bool = False,
    uv: str | None = None,
) -> BuildPlan:
    """Validate preconditions and return the command plan; does not run anything."""
    require_trusted(workspace.root, workspace.config.node_modules)
    uv_bin = uv or find_uv()
    try:
        lock_text = lock_text_from_environment(workspace.artifacts, environment)
    except KeyError as exc:
        raise IsolatedReproductionError(
            "This run has no environment lock. Only runs recorded by NeuroWeave 0.2.1+ "
            "(with a pinned lock) can be reproduced in a rebuilt environment. Re-run the "
            "workflow once, then retry.") from exc
    lock = environment.get("lock") if isinstance(environment, dict) else None
    if not isinstance(lock, dict) or not isinstance(lock.get("hash"), str):
        raise IsolatedReproductionError("This run has no environment lock.")
    lock_hash = lock["hash"]
    local_names = list(lock.get("local") or [])
    missing = []
    for name, path in _local_paths_from_lock(lock_text, local_names).items():
        if not path.exists():
            missing.append(f"{name} ({path})")
    if missing:
        raise IsolatedReproductionError(
            "These local packages from the original environment are no longer at their "
            "recorded paths, so the environment cannot be rebuilt:\n  - "
            + "\n  - ".join(missing))

    neuroweave_meta = lock.get("neuroweave") if isinstance(lock.get("neuroweave"), dict) else {}
    neuroweave_source = _resolve_neuroweave_source(neuroweave_meta)
    python_version = _recorded_python_version(environment)
    env_dir = env_dir_for(workspace, lock_hash)
    lock_path = env_dir / "requirements.lock"
    python = str(env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))

    commands: list[list[str]] = [
        [uv_bin, "venv", "--python", python_version, str(env_dir)],
    ]
    install = [uv_bin, "pip", "install", "--python", python, "--no-deps"]
    if not allow_build:
        install.append("--no-build")
    install.extend(["-r", str(lock_path)])
    commands.append(install)
    nw_install = [uv_bin, "pip", "install", "--python", python]
    if not allow_build:
        # NeuroWeave itself is a source tree; allow building just that one package.
        nw_install.append("--no-deps")
    nw_install.append(str(neuroweave_source))
    commands.append(nw_install)

    return BuildPlan(
        env_dir=env_dir, python_version=python_version, lock_path=lock_path,
        lock_hash=lock_hash, neuroweave_source=neuroweave_source, allow_build=allow_build,
        commands=commands,
    )


def build_environment(
    workspace: Workspace,
    environment: dict[str, Any],
    *,
    allow_build: bool = False,
    rebuild: bool = False,
    runner: CommandRunner | None = None,
    uv: str | None = None,
    log: Callable[[str], None] | None = None,
) -> Path:
    """Create (or reuse) a virtual environment matching ``environment``'s lock.

    Returns the path to the environment directory. A ``.complete`` marker containing the
    lock hash means a later call reuses it unless ``rebuild`` is true.
    """
    emit = log or (lambda _message: None)
    run = runner or _default_runner
    plan = plan_environment(workspace, environment, allow_build=allow_build, uv=uv)
    marker = plan.env_dir / ".complete"
    python = plan.env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    if not rebuild and marker.is_file() and python.is_file():
        try:
            if marker.read_text(encoding="utf-8").strip() == plan.lock_hash:
                emit(f"Reusing rebuilt environment at {plan.env_dir}")
                return plan.env_dir
        except OSError:
            pass

    if plan.env_dir.exists():
        shutil.rmtree(plan.env_dir)
    plan.env_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_text = lock_text_from_environment(workspace.artifacts, environment)
    if not allow_build:
        emit("Installing packages with --no-build (source builds refused). "
             "Pass --allow-build to permit them.")

    for index, command in enumerate(plan.commands):
        emit("$ " + " ".join(command))
        result = run(command, workspace.root)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise IsolatedReproductionError(
                f"Command failed ({result.returncode}): {' '.join(command)}\n{detail}")
        if result.stdout:
            emit(result.stdout.rstrip())
        if result.stderr:
            emit(result.stderr.rstrip())
        # Write the lock into the fresh venv before the pip install that reads it.
        if index == 0:
            plan.lock_path.write_text(lock_text, encoding="utf-8")

    marker.write_text(plan.lock_hash + "\n", encoding="utf-8")
    emit(f"Environment ready at {plan.env_dir}")
    return plan.env_dir


def python_in(env_dir: Path) -> Path:
    candidate = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not candidate.is_file():
        raise IsolatedReproductionError(f"No Python interpreter in rebuilt environment {env_dir}.")
    return candidate


def prepare_isolated_reproduction(workspace: Workspace, run_id: str):
    """Create a PENDING reproduction run linked to ``run_id``; return (original, pending)."""
    original = workspace.db.get_run(run_id)
    if original is None:
        raise KeyError(f"Run '{run_id}' does not exist.")
    if original.environment is None:
        raise IsolatedReproductionError(
            f"Run '{run_id}' has no recorded environment, so it cannot be rebuilt.")
    workflow = workspace.load_snapshot(original.snapshot_hash)
    pending = prepare_run(
        workspace, workflow, seed=original.seed, use_cache=False,
        trigger="reproduce-isolated", reproduces_run_id=original.id,
    )
    return original, pending


def worker_command(env_dir: Path, workspace: Workspace, run_id: str) -> list[str]:
    """Build the worker argv. Call ``python_in`` first if the interpreter must exist."""
    python = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return [
        str(python), "-P", "-m", "neuroweave.runtime.worker",
        "--workspace", str(workspace.root), "--run-id", run_id,
    ]


def reproduce_isolated(
    workspace: Workspace,
    run_id: str,
    *,
    allow_build: bool = False,
    rebuild: bool = False,
    runner: CommandRunner | None = None,
    uv: str | None = None,
    log: Callable[[str], None] | None = None,
    worker_runner: CommandRunner | None = None,
):
    """Rebuild the environment for ``run_id`` and execute a reproduction inside it.

    Returns ``(pending_run, environment_dir)``. The pending run has already been executed
    by the worker when this returns; load a ``ReproductionReport`` with
    ``reproduction_report(workspace, pending.id)``.
    """
    from neuroweave.experiments import reproduction_report

    emit = log or (lambda _message: None)
    original, pending = prepare_isolated_reproduction(workspace, run_id)
    assert original.environment is not None
    env_dir = build_environment(
        workspace, original.environment, allow_build=allow_build, rebuild=rebuild,
        runner=runner, uv=uv, log=emit,
    )
    python_in(env_dir)  # confirm the rebuilt interpreter exists before launching
    command = worker_command(env_dir, workspace, pending.id)
    emit("$ " + " ".join(command))
    run = worker_runner or runner or _default_runner
    result = run(command, workspace.root)
    if result.stdout:
        emit(result.stdout.rstrip())
    if result.stderr:
        emit(result.stderr.rstrip())
    # Always build the report: a failed worker still leaves a FAILED run record.
    report = reproduction_report(workspace, pending.id)
    if result.returncode != 0 and report.verdict == "pending":
        raise IsolatedReproductionError(
            f"Isolated worker exited with code {result.returncode} without finishing the run.")
    return report, env_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--run-id", required=True,
                        help="Original run to reproduce in a rebuilt environment.")
    parser.add_argument("--rebuild", action="store_true",
                        help="Discard any cached rebuilt environment for this lock.")
    parser.add_argument("--allow-build", action="store_true",
                        help="Allow source builds while installing packages (off by default).")
    args = parser.parse_args(argv)

    workspace = Workspace(Path(args.workspace))

    def log(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    try:
        report, env_dir = reproduce_isolated(
            workspace, args.run_id, allow_build=args.allow_build, rebuild=args.rebuild,
            log=log,
        )
    except (IsolatedReproductionError, KeyError) as exc:
        print(f"[neuroweave] isolated reproduction failed: {exc}", file=sys.stderr)
        return 2
    print(f"[neuroweave] isolated environment: {env_dir}", file=sys.stderr)
    print(f"[neuroweave] reproduction {report.reproduction_run_id}: {report.verdict} "
          f"(environment_match={report.environment_match})", file=sys.stderr)
    return 0 if report.verdict == "reproduced" else 1


if __name__ == "__main__":
    sys.exit(main())
