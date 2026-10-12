"""Bundled sample project and guided walkthrough for first-time users."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

# Files shipped inside the package (must stay identical to examples/research_demo/).
ASSET_FILES = (
    "demo_nodes.py",
    "workflow.json",
    "data/field_trial.csv",
)


def assets_root() -> Path:
    """Filesystem path to the packaged tutorial assets."""
    return Path(str(resources.files("neuroweave.tutorial") / "assets"))


def asset_bytes(relative: str) -> bytes:
    return (assets_root() / relative).read_bytes()
