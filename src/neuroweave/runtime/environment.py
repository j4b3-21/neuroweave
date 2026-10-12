"""Capture of the runtime environment relevant to reproducing a run.

Environment variables are deliberately not recorded: they commonly contain credentials.

Each run also stores a pinned, installable lock of the packages present at execution time.
The lock is content-addressed in the artifact store so later reproductions can rebuild the
same package set with ``uv`` (see ``neuroweave.runtime.isolated``).
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from neuroweave.store.artifacts import ArtifactStore
from neuroweave.store.files import utc_now

# Project lockfiles we recognise and archive alongside the run.
_PROJECT_LOCK_NAMES = ("uv.lock", "pylock.toml", "poetry.lock")
_REQUIREMENTS_GLOB = "requirements*.txt"


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


# ---------------------------------------------------------------------- pinned lock


@dataclass(frozen=True)
class LockEntry:
    """One installable requirement line, plus whether it depends on a local path."""

    name: str
    line: str
    local: bool = False
    source: str | None = None


@dataclass
class EnvironmentLock:
    """Deterministic, installable snapshot of the current Python environment."""

    text: str
    local: list[str] = field(default_factory=list)
    neuroweave: dict[str, str] = field(default_factory=dict)

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def _read_direct_url(dist: importlib.metadata.Distribution) -> dict[str, Any] | None:
    try:
        raw = dist.read_text("direct_url.json")
    except (FileNotFoundError, OSError):
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _vcs_requirement(name: str, info: dict[str, Any]) -> str | None:
    url = info.get("url")
    if not isinstance(url, str) or not url:
        return None
    commit = info.get("commit_id")
    vcs = info.get("vcs") or "git"
    # Prefer an explicit VCS URL form that pip/uv can reinstall.
    if "://" in url and not url.startswith(f"{vcs}+"):
        url = f"{vcs}+{url}"
    if isinstance(commit, str) and commit:
        if "@" in url.rsplit("/", 1)[-1]:
            # Already has a ref; append commit as fragment when missing.
            if "#commit=" not in url and "#" not in url:
                url = f"{url}#{commit}"
        else:
            url = f"{url}@{commit}"
    return f"{name} @ {url}"


def _file_requirement(name: str, url: str) -> tuple[str, bool]:
    """Return (requirement line, is_local). Local paths are kept as absolute file URLs."""
    parsed = urlparse(url)
    if parsed.scheme == "file":
        path = Path(urlparse(url).path)
        # Normalise to an absolute file URL so rebuilds can check existence.
        absolute = path if path.is_absolute() else Path(path).resolve()
        return f"{name} @ {absolute.as_uri()}", True
    return f"{name} @ {url}", False


def _classify_distribution(dist: importlib.metadata.Distribution) -> LockEntry | None:
    name = dist.metadata.get("Name")
    if not name:
        return None
    version = dist.version
    direct = _read_direct_url(dist)
    if direct is None:
        return LockEntry(name=name, line=f"{name}=={version}")

    url = direct.get("url")
    if not isinstance(url, str):
        return LockEntry(name=name, line=f"{name}=={version}")

    vcs = direct.get("vcs_info")
    if isinstance(vcs, dict):
        line = _vcs_requirement(name, {**vcs, "url": url})
        if line:
            return LockEntry(name=name, line=line, source=url)

    dir_info = direct.get("dir_info")
    if isinstance(dir_info, dict) or url.startswith("file:"):
        line, local = _file_requirement(name, url)
        return LockEntry(name=name, line=line, local=local, source=url)

    # Archive URL (http/s wheel or sdist) with an optional hash.
    hashes = direct.get("hashes") if isinstance(direct.get("hashes"), dict) else {}
    sha = hashes.get("sha256") if isinstance(hashes, dict) else None
    if isinstance(sha, str) and sha:
        return LockEntry(name=name, line=f"{name} @ {url}#sha256={sha}", source=url)
    return LockEntry(name=name, line=f"{name} @ {url}", source=url)


def environment_lock(
    distributions: list[importlib.metadata.Distribution] | None = None,
) -> EnvironmentLock:
    """Build a deterministic, installable lock of the current (or given) distributions.

    NeuroWeave itself is excluded from the pinned lines and recorded separately, because
    isolated reproduction installs it specially (from its recorded source, or from the
    currently running NeuroWeave tree).
    """
    dists = list(distributions) if distributions is not None else list(
        importlib.metadata.distributions())
    entries: list[LockEntry] = []
    neuroweave_meta: dict[str, str] = {}
    for dist in dists:
        entry = _classify_distribution(dist)
        if entry is None:
            continue
        if entry.name.lower() == "neuroweave":
            neuroweave_meta = {
                "version": dist.version,
                "source": entry.source or entry.line,
            }
            if entry.local and entry.source:
                neuroweave_meta["local"] = "true"
            continue
        entries.append(entry)

    entries.sort(key=lambda e: e.name.lower())
    text = "\n".join(e.line for e in entries)
    if text:
        text += "\n"
    local = sorted({e.name.lower() for e in entries if e.local})
    if not neuroweave_meta:
        from neuroweave import __version__

        neuroweave_meta = {"version": __version__, "source": "unknown"}
    return EnvironmentLock(text=text, local=local, neuroweave=neuroweave_meta)


def project_lockfiles(project_root: Path) -> list[tuple[str, bytes]]:
    """Return (relative path, contents) for recognised lockfiles in the project root."""
    root = project_root.resolve()
    found: list[tuple[str, bytes]] = []
    for name in _PROJECT_LOCK_NAMES:
        path = root / name
        if path.is_file():
            found.append((name, path.read_bytes()))
    for path in sorted(root.glob(_REQUIREMENTS_GLOB)):
        if path.is_file() and path.name not in {p for p, _ in found}:
            found.append((path.name, path.read_bytes()))
    return found


def capture_environment(
    project_root: Path,
    artifacts: ArtifactStore | None = None,
) -> dict[str, Any]:
    """Capture the runtime environment, optionally storing a pinned lock in ``artifacts``."""
    from neuroweave import __version__

    env: dict[str, Any] = {
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

    if artifacts is not None:
        lock = environment_lock()
        lock_hash, _ = artifacts.put_bytes(lock.text.encode("utf-8"))
        env["lock"] = {
            "format": "requirements",
            "hash": lock_hash,
            "local": lock.local,
            "neuroweave": lock.neuroweave,
        }
        project: list[dict[str, str]] = []
        for rel, data in project_lockfiles(project_root):
            digest, _ = artifacts.put_bytes(data)
            project.append({"path": rel, "hash": digest})
        if project:
            env["project_lockfiles"] = project
    return env


def python_identity() -> str:
    major, minor = sys.version_info[:2]
    return f"{platform.python_implementation()}-{major}.{minor}"


def lock_text_from_environment(artifacts: ArtifactStore, environment: dict[str, Any]) -> str:
    """Load the stored lock text for a run's environment, or raise KeyError."""
    lock = environment.get("lock") if isinstance(environment, dict) else None
    if not isinstance(lock, dict) or not lock.get("hash"):
        raise KeyError("This run has no environment lock.")
    return artifacts.get_bytes(lock["hash"]).decode("utf-8")
