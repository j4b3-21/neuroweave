"""Which project directories the user has agreed to run code from.

Opening a project imports the Python modules listed in its ``project.json`` (to build the node
catalogue, validate workflows and run them), and that code runs with the user's permissions.
Projects created on this machine with ``nw init`` are trusted automatically; a project that
arrives some other way (a cloned repository, an archive, a shared folder) must be trusted once,
explicitly, before any of its code is imported. Trust is recorded per resolved directory path in
a file outside the project, so a project cannot mark itself as trusted.

This is a confirmation step, not isolation: trusted code still runs unrestricted.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from neuroweave.store.files import atomic_write_text, utc_now

TRUST_FILE_ENV = "NEUROWEAVE_TRUST_FILE"


class UntrustedProjectError(PermissionError):
    def __init__(self, root: Path):
        self.root = root
        super().__init__(
            f"The project at {root} is not trusted, so its node modules were not imported. "
            "Trusting a project lets its Python code run with your user permissions. If you "
            f"know where it came from, trust it with `nw --project {_quote(root)} trust`.")


def _quote(path: Path) -> str:
    text = str(path)
    return f'"{text}"' if any(c.isspace() for c in text) else text


def trust_file() -> Path:
    override = os.environ.get(TRUST_FILE_ENV)
    if override:
        return Path(override)
    config_home = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(config_home) / "neuroweave" / "trusted-projects.json"


def _read() -> dict[str, dict]:
    """Trusted projects by path. A missing or unreadable file trusts nothing."""
    try:
        data = json.loads(trust_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    projects = data.get("projects") if isinstance(data, dict) else None
    return projects if isinstance(projects, dict) else {}


def _write(projects: dict[str, dict]) -> None:
    path = trust_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps({"projects": projects}, indent=2, sort_keys=True) + "\n")


def _key(root: Path) -> str:
    return str(Path(root).resolve())


def is_trusted(root: Path) -> bool:
    return _key(root) in _read()


def trust_project(root: Path) -> None:
    projects = _read()
    projects.setdefault(_key(root), {"trusted_at": utc_now()})
    _write(projects)


def revoke_project(root: Path) -> bool:
    projects = _read()
    removed = projects.pop(_key(root), None) is not None
    if removed:
        _write(projects)
    return removed


def needs_trust(root: Path, node_modules: list[str]) -> bool:
    """A project with no node modules imports no project code, so it needs no trust."""
    return bool(node_modules) and not is_trusted(root)


def require_trusted(root: Path, node_modules: list[str]) -> None:
    if needs_trust(root, node_modules):
        raise UntrustedProjectError(Path(root).resolve())
