"""Capture of the runtime environment relevant to reproducing a run.

Environment variables are deliberately not recorded: they commonly contain credentials.
"""

from __future__ import annotations

import importlib.metadata
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from neuroweave.store.files import utc_now


def _git(project_root: Path, *args: str) -> str | None:
    # A repository's own config can name a command that `git status` runs (core.fsmonitor).
    try:
        result = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-C", str(project_root), *args],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def git_info(project_root: Path) -> dict[str, Any] | None:
    commit = _git(project_root, "rev-parse", "HEAD")
    if commit is None:
        return None
    status = _git(project_root, "status", "--porcelain", "--untracked-files=no")
    return {
        "commit": commit,
        "branch": _git(project_root, "rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(status),
    }


def installed_packages() -> dict[str, str]:
    packages: dict[str, str] = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name")
        if name:
            packages[name.lower()] = dist.version
    return dict(sorted(packages.items()))


def capture_environment(project_root: Path) -> dict[str, Any]:
    from neuroweave import __version__

    return {
        "captured_at": utc_now(),
        "neuroweave": __version__,
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "git": git_info(project_root),
        "packages": installed_packages(),
    }


def python_identity() -> str:
    major, minor = sys.version_info[:2]
    return f"{platform.python_implementation()}-{major}.{minor}"
