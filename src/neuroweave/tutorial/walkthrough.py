"""Guided terminal walkthrough that runs real ``nw`` commands on a sample project."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from neuroweave.kernel.serialization import load_workflow
from neuroweave.onboarding import mark_completed
from neuroweave.store.workspace import Workspace
from neuroweave.tutorial import ASSET_FILES, asset_bytes

DEFAULT_DIR = Path.home() / "neuroweave-tutorial"
WORKFLOW_ID = "rainfall-yield"


class TutorialError(RuntimeError):
    pass


def default_tutorial_dir() -> Path:
    return DEFAULT_DIR


def _copy_assets(target: Path) -> None:
    for relative in ASSET_FILES:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(asset_bytes(relative))


def materialize_tutorial_project(directory: Path, *, reset: bool = False) -> Workspace:
    """Create or refresh the tutorial project at ``directory``."""
    directory = directory.expanduser().resolve()
    if directory.exists() and any(directory.iterdir()):
        if not reset:
            if (directory / ".neuroweave").is_dir():
                ws = Workspace(directory)
                if not ws.config.tutorial:
                    raise TutorialError(
                        f"{directory} already exists and is not a NeuroWeave tutorial project. "
                        "Choose another --dir, or pass --reset only for a tutorial folder.")
                return ws
            raise TutorialError(
                f"{directory} already exists and is not empty. Pass --reset to recreate a "
                "tutorial project there, or choose another --dir.")
        # --reset: only delete a confirmed tutorial project.
        if (directory / ".neuroweave").is_dir():
            ws = Workspace(directory)
            if not ws.config.tutorial:
                raise TutorialError(
                    f"Refusing to --reset {directory}: it is not marked as a tutorial project.")
        elif any(directory.iterdir()):
            raise TutorialError(
                f"Refusing to --reset {directory}: it is not a NeuroWeave tutorial project.")
        shutil.rmtree(directory)

    directory.mkdir(parents=True, exist_ok=True)
    _copy_assets(directory)
    ws = Workspace.init(directory, name="NeuroWeave tutorial", node_modules=["demo_nodes"])
    config = ws.config
    config.tutorial = True
    ws.save_config(config)
    workflow = load_workflow((directory / "workflow.json").read_text(encoding="utf-8"))
    ws.save_workflow(workflow)
    return ws


def _nw(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "neuroweave.cli", "--project", str(directory), *args],
        capture_output=True, text=True, check=False, cwd=str(directory),
    )


def _require_ok(result: subprocess.CompletedProcess[str], what: str) -> str:
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise TutorialError(f"{what} failed (exit {result.returncode}):\n{detail}")
    return result.stdout


Pause = Callable[[str], None]
Echo = Callable[[str], None]


def _default_pause(message: str) -> None:
    try:
        input(message)
    except EOFError:
        pass


def run_chapters(
    directory: Path,
    *,
    yes: bool = False,
    echo: Echo | None = None,
    pause: Pause | None = None,
) -> dict[str, str]:
    """Run the terminal chapters. Returns ids of interesting runs for later steps."""
    out = echo or print
    wait = (lambda _m: None) if yes else (pause or _default_pause)
    ids: dict[str, str] = {}

    def chapter(title: str, body: str) -> None:
        out("")
        out("=" * 60)
        out(title)
        out("=" * 60)
        out(body)
        wait("Press Enter to continue… ")

    chapter(
        "1. What NeuroWeave is",
        "NeuroWeave turns analysis steps into a typed workflow graph. Every run records the\n"
        "exact graph, parameters, seeds, outputs, logs and environment.\n\n"
        "There is no sandbox: node code runs with your user permissions. Only open projects\n"
        "and run code you trust.",
    )

    out("\n$ nw nodes")
    nodes_out = _require_ok(_nw(directory, "nodes"), "nw nodes")
    out(nodes_out.rstrip())
    chapter(
        "2. Nodes",
        "A node is an ordinary typed Python function decorated with @node. Parameters become\n"
        "input ports; the return annotation becomes the output. Look at demo_nodes.py in this\n"
        "folder for the seven steps of the rainfall/yield study.",
    )

    out("\n$ nw workflows list")
    out(_require_ok(_nw(directory, "workflows", "list"), "nw workflows list").rstrip())
    out("\n$ nw validate rainfall-yield")
    out(_require_ok(_nw(directory, "validate", WORKFLOW_ID), "nw validate").rstrip())
    chapter(
        "3. Workflows",
        "A workflow connects nodes into a directed graph. Validation checks that every input\n"
        "is connected or has a parameter, and that port types are compatible.",
    )

    out("\n$ nw run rainfall-yield")
    first = _require_ok(_nw(directory, "run", WORKFLOW_ID), "nw run")
    out(first.rstrip())
    for line in first.splitlines():
        if line.startswith("Run ") and "SUCCEEDED" in line:
            ids["first"] = line.split()[1].rstrip(":")
            break
    chapter(
        "4. First run",
        "Each run freezes the workflow as an immutable snapshot and records every node's\n"
        "inputs, outputs, code hash, seed and logs under .neuroweave/.",
    )

    out("\n$ nw run rainfall-yield   # again")
    second = _require_ok(_nw(directory, "run", WORKFLOW_ID), "nw run (cache)")
    out(second.rstrip())
    chapter(
        "5. Cache reuse",
        "When nothing changed, every node is reused from the cache. Reuse is always visible:\n"
        "the Studio shows Reused, and the run record points at the earlier execution.",
    )

    # Change a downstream parameter through the workspace API (not the CLI), then run.
    ws = Workspace(directory)
    workflow = ws.load_workflow(WORKFLOW_ID)
    workflow.node("bootstrap").params["resamples"] = 300
    ws.save_workflow(workflow)
    out("\n(changed bootstrap.resamples from 500 to 300)")
    out("$ nw run rainfall-yield")
    third = _require_ok(_nw(directory, "run", WORKFLOW_ID), "nw run (incremental)")
    out(third.rstrip())
    for line in third.splitlines():
        if line.startswith("Run ") and ":" in line:
            ids["changed"] = line.split()[1].rstrip(":")
            break
    chapter(
        "6. Incremental execution",
        "Only the edited node and the nodes that depend on it re-execute. Upstream nodes\n"
        "are reused. In this demo that is usually bootstrap and report re-running, with the\n"
        "other five reused.",
    )

    if "first" in ids and "changed" in ids:
        out(f"\n$ nw compare {ids['first']} {ids['changed']}")
        out(_require_ok(
            _nw(directory, "compare", ids["first"], ids["changed"]), "nw compare").rstrip())
    chapter(
        "7. Comparison",
        "nw compare shows parameter changes, which outputs differ, and metric deltas with\n"
        "their declared goal direction. It never picks a winner for you.",
    )

    target = ids.get("changed") or ids.get("first")
    if target:
        out(f"\n$ nw reproduce {target}")
        repro = _nw(directory, "reproduce", target)
        out((repro.stdout or repro.stderr).rstrip())
        if repro.returncode != 0 and "Verdict: reproduced" not in (repro.stdout or ""):
            # Still continue; the chapter explains the meaning either way.
            out(f"(exit {repro.returncode})")
    chapter(
        "8. Reproduction",
        "nw reproduce re-runs the snapshot with the same seed and no cache, then checks that\n"
        "every output is byte-identical (exact SHA-256). The environment badge tells you\n"
        "whether the lock matched. `nw reproduce --isolated` rebuilds the packages with uv\n"
        "first (needs network; skipped here). It does not recreate the OS or system libraries.",
    )

    out("\n$ nw artifacts --run " + (target or ""))
    if target:
        arts = _require_ok(_nw(directory, "artifacts", "--run", target), "nw artifacts")
        out(arts.rstrip())
        # Pick a report artifact id if present.
        report_id = None
        for line in arts.splitlines():
            if "report" in line and "output" in line:
                report_id = line.split()[0]
                break
        if report_id:
            out(f"\n$ nw lineage {report_id}")
            out(_require_ok(_nw(directory, "lineage", report_id), "nw lineage").rstrip())
    out("\n$ nw verify --all")
    out(_require_ok(_nw(directory, "verify", "--all"), "nw verify").rstrip())
    chapter(
        "9. Lineage and integrity",
        "nw lineage traces what produced (or used) an artifact. nw verify re-hashes stored\n"
        "bytes to detect tampering or corruption.",
    )

    out("\nCheat sheet:")
    out("  nw nodes / nw validate / nw run / nw compare / nw reproduce [--isolated]")
    out("  nw env show / nw lineage / nw verify / nw studio")
    out(f"\nTutorial project: {directory}")
    mark_completed()
    return ids


def open_studio(directory: Path, *, port: int = 8765, open_browser: bool = True) -> None:
    """Start the Studio for the tutorial project with the guided tour hash."""
    import threading
    import webbrowser

    import uvicorn

    from neuroweave.server.app import STATIC_DIR, create_app

    workspace = Workspace(directory)
    if not (STATIC_DIR / "index.html").exists():
        raise TutorialError(
            "Studio UI is not built. Build it with "
            "`npm --prefix apps/studio install && npm --prefix apps/studio run build`.")
    url = f"http://127.0.0.1:{port}/#tour=1"
    print(f"Opening NeuroWeave Studio with the guided tour at {url}")
    print("Node code runs with your user permissions (no sandbox). Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(workspace.root), host="127.0.0.1", port=port, log_level="warning")


def run_tutor(
    directory: Path | None = None,
    *,
    reset: bool = False,
    yes: bool = False,
    no_studio: bool = False,
    studio_only: bool = False,
    port: int = 8765,
    open_browser: bool = True,
) -> Path:
    """Entry point used by the CLI."""
    target = (directory or default_tutorial_dir()).expanduser()
    if studio_only:
        if not (target / ".neuroweave").is_dir():
            raise TutorialError(
                f"No tutorial project at {target}. Run `nw tutor` without --studio-only first.")
        open_studio(target, port=port, open_browser=open_browser)
        return target.resolve()

    ws = materialize_tutorial_project(target, reset=reset)
    print(f"Tutorial project ready at {ws.root}")
    run_chapters(ws.root, yes=yes)
    if not no_studio:
        open_studio(ws.root, port=port, open_browser=open_browser)
    else:
        print(f"\nSkipped Studio. Open it later with: nw --project {ws.root} tutor --studio-only")
    return ws.root
