"""Discover a project's node catalogue in a child process.

``python -m neuroweave.runtime.catalog --workspace <root>`` prints JSON
``{"definitions": [...], "errors": [...]}`` on stdout. Output printed by user modules during
import is redirected to stderr so it cannot corrupt the JSON.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

from neuroweave.sdk.registry import default_registry, load_node_modules
from neuroweave.store.workspace import Workspace


def discover(workspace: Workspace) -> dict:
    with contextlib.redirect_stdout(sys.stderr):
        errors = load_node_modules(workspace.config.node_modules, workspace.root)
    return {
        "definitions": [d.model_dump(mode="json") for d in default_registry.definitions()],
        "errors": [e.model_dump(mode="json") for e in errors],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args(argv)
    result = discover(Workspace(Path(args.workspace)))
    sys.stdout.write(json.dumps(result))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
