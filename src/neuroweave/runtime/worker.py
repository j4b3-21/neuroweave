"""Child-process entry point that executes one prepared run.

``python -m neuroweave.runtime.worker --workspace <root> --run-id <id>``

Running each Studio-launched run in its own process means user code never executes inside
the API server, freshly edited node modules are always used, and a run can be cancelled
(SIGTERM interrupts the running node; the server escalates to SIGKILL if needed). This is
process isolation, not a security sandbox.
"""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from neuroweave.runtime.executor import RunCancelled, cancellation, execute_run
from neuroweave.sdk.registry import default_registry, load_node_modules
from neuroweave.store.workspace import Workspace


def _on_terminate(signum, frame) -> None:  # noqa: ARG001
    cancellation.requested = True
    if cancellation.in_node:
        raise RunCancelled()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)

    signal.signal(signal.SIGTERM, _on_terminate)
    workspace = Workspace(Path(args.workspace))
    errors = load_node_modules(workspace.config.node_modules, workspace.root)
    for error in errors:
        print(f"[neuroweave] failed to import {error.module}: {error.error}", file=sys.stderr)
    run = execute_run(workspace, args.run_id, default_registry, module_errors=errors)
    print(f"[neuroweave] run {run.id} finished: {run.status}", file=sys.stderr)
    return 0 if run.status == "SUCCEEDED" else 1


if __name__ == "__main__":
    sys.exit(main())
