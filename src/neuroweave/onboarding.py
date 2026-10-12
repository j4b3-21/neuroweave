"""First-run tutorial offer state (outside any project)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from neuroweave.store.files import atomic_write_text, utc_now

ONBOARDING_FILE_ENV = "NEUROWEAVE_ONBOARDING_FILE"
NO_ONBOARDING_ENV = "NEUROWEAVE_NO_ONBOARDING"


def onboarding_file() -> Path:
    override = os.environ.get(ONBOARDING_FILE_ENV)
    if override:
        return Path(override)
    config_home = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(config_home) / "neuroweave" / "onboarding.json"


def _read() -> dict[str, Any]:
    try:
        data = json.loads(onboarding_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(data: dict[str, Any]) -> None:
    path = onboarding_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def should_offer_tutorial(*, command: str | None = None, interactive: bool = False) -> bool:
    """True only on the first interactive CLI use, never under CI or for ``tutor`` itself."""
    if not interactive:
        return False
    if command == "tutor":
        return False
    if os.environ.get("CI"):
        return False
    if os.environ.get(NO_ONBOARDING_ENV):
        return False
    state = _read()
    if state.get("prompted_at") or state.get("completed_at") or state.get("declined_at"):
        return False
    return True


def mark_prompted() -> None:
    state = _read()
    state.setdefault("prompted_at", utc_now())
    _write(state)


def mark_declined() -> None:
    state = _read()
    state["prompted_at"] = state.get("prompted_at") or utc_now()
    state["declined_at"] = utc_now()
    _write(state)


def mark_completed() -> None:
    state = _read()
    state["prompted_at"] = state.get("prompted_at") or utc_now()
    state["completed_at"] = utc_now()
    _write(state)


def mark_studio_welcomed() -> None:
    """Record that the Studio welcome dialog was shown (CLI-side; Studio uses localStorage)."""
    state = _read()
    state["studio_welcomed_at"] = utc_now()
    _write(state)
