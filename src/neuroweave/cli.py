"""The ``nw`` command line interface."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError

from neuroweave.kernel.serialization import dump_workflow, load_workflow
from neuroweave.kernel.validation import validate_workflow
from neuroweave.store.trust import (
    UntrustedProjectError,
    needs_trust,
    revoke_project,
    trust_project,
)
from neuroweave.store.workspace import (
    WorkflowNotFoundError,
    Workspace,
    WorkspaceNotFoundError,
    initialize_workspace,
)

app = typer.Typer(add_completion=False, help="NeuroWeave command line interface.",
                  no_args_is_help=True)
workflows_app = typer.Typer(help="Manage workflow definitions.", no_args_is_help=True)
app.add_typer(workflows_app, name="workflows")

_state: dict[str, Any] = {"project": None}


def _fail(message: str) -> None:
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(1)


def _workspace() -> Workspace:
    try:
        return Workspace.open(_state["project"])
    except WorkspaceNotFoundError as exc:
        _fail(str(exc))
        raise  # unreachable


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _confirm_trust(workspace: Workspace) -> bool:
    """Ask once before importing code from a project that has not been trusted yet."""
    if not needs_trust(workspace.root, workspace.config.node_modules):
        return True
    if _interactive():
        typer.echo(f"This project has not been trusted on this machine: {workspace.root}\n"
                   "Opening it imports its node modules ("
                   + ", ".join(workspace.config.node_modules)
                   + "), which run with your user permissions.")
        if typer.confirm("Do you trust this project's code?", default=False):
            trust_project(workspace.root)
            typer.echo("Trusted. You will not be asked again for this directory.")
            return True
    return False


def _load_registry(workspace: Workspace):
    from neuroweave.sdk.registry import default_registry, load_node_modules

    if not _confirm_trust(workspace):
        _fail(str(UntrustedProjectError(workspace.root)))
    errors = load_node_modules(workspace.config.node_modules, workspace.root)
    for error in errors:
        typer.echo(f"Warning: could not import node module {error.module}: {error.error}",
                   err=True)
    return default_registry


def _load_workflow(workspace: Workspace, workflow_id: str):
    try:
        return workspace.load_workflow(workflow_id)
    except (WorkflowNotFoundError, ValueError) as exc:
        _fail(str(exc).strip("'\""))


def _get_run(workspace: Workspace, run_id: str):
    run = workspace.db.get_run(run_id)
    if run is None:
        _fail(f"Run '{run_id}' does not exist. List runs with `nw runs`.")
    return run


def _short(value: str | None, length: int = 12) -> str:
    return (value or "-")[:length]


def _table(headers: list[str], rows: list[list[Any]]) -> None:
    cells = [[str(c) for c in headers]] + [[("-" if c is None else str(c)) for c in r]
                                           for r in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(headers))]
    for index, row in enumerate(cells):
        typer.echo("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
        if index == 0:
            typer.echo("  ".join("-" * w for w in widths))


@app.callback()
def cli(
    project: Path | None = typer.Option(
        None, "--project", "-C", help="Project directory (default: search upward from cwd)."
    ),
) -> None:
    """NeuroWeave command line interface."""
    _state["project"] = project


# ------------------------------------------------------------------------------ project


@app.command()
def init(
    name: str | None = typer.Option(None, help="Project name (default: directory name)."),
    node_module: list[str] = typer.Option(
        [], "--node-module", "-m", help="Python module containing @node functions."
    ),
) -> None:
    """Initialize the local NeuroWeave workspace."""
    base = _state["project"] or Path.cwd()
    result = initialize_workspace(base, name=name, node_modules=node_module)
    for line in result.summary_lines():
        typer.echo(line)
    workspace = Workspace(base)
    if needs_trust(workspace.root, workspace.config.node_modules):
        typer.echo("This project already existed and is not trusted yet; its node modules will "
                   "not be imported until you run `nw trust`.")


@app.command()
def trust(
    revoke: bool = typer.Option(False, "--revoke", help="Stop trusting this project."),
) -> None:
    """Allow this project's node modules to be imported (they run with your permissions)."""
    workspace = _workspace()
    if revoke:
        removed = revoke_project(workspace.root)
        typer.echo(f"{'No longer trusting' if removed else 'Was not trusting'} {workspace.root}")
        return
    trust_project(workspace.root)
    typer.echo(f"Trusted {workspace.root}. Its node modules ("
               + (", ".join(workspace.config.node_modules) or "none configured")
               + ") will be imported when you open, validate or run its workflows.")


@app.command()
def nodes(as_json: bool = typer.Option(False, "--json", help="Print JSON.")) -> None:
    """List the node definitions available to this project."""
    workspace = _workspace()
    registry = _load_registry(workspace)
    definitions = registry.definitions()
    if as_json:
        typer.echo(json.dumps([d.model_dump(mode="json") for d in definitions], indent=2))
        return
    if not definitions:
        typer.echo("No nodes registered. Add module names to node_modules in "
                   f"{workspace.project_file}.")
        return
    rows = []
    for d in definitions:
        inputs = ", ".join(f"{p.name}: {p.type}" for p in d.inputs)
        outputs = ", ".join(f"{p.name}: {p.type}" for p in d.outputs) or "-"
        rows.append([d.id, d.version, f"({inputs}) -> {outputs}"])
    _table(["id", "version", "signature"], rows)


# ------------------------------------------------------------------------------ workflows


@workflows_app.command("list")
def workflows_list() -> None:
    """List workflows in this project."""
    workspace = _workspace()
    items = workspace.list_workflows()
    if not items:
        typer.echo("No workflows yet. Create one in the Studio or `nw workflows import FILE`.")
        return
    _table(["id", "name", "nodes", "edges"],
           [[w.id, w.name, len(w.nodes), len(w.edges)] for w in items])


@workflows_app.command("import")
def workflows_import(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    force: bool = typer.Option(False, help="Overwrite an existing workflow with the same id."),
) -> None:
    """Import a workflow JSON file into the project."""
    workspace = _workspace()
    try:
        workflow = load_workflow(file.read_text(encoding="utf-8"))
    except (ValueError, ValidationError) as exc:
        _fail(f"{file} is not a valid workflow: {exc}")
    if workspace.workflow_exists(workflow.id) and not force:
        _fail(f"Workflow '{workflow.id}' already exists; use --force to overwrite.")
    path = workspace.save_workflow(workflow)
    typer.echo(f"Imported workflow '{workflow.id}' to {path}")


@workflows_app.command("export")
def workflows_export(
    workflow_id: str,
    output: Path | None = typer.Option(None, "--output", "-o", help="File (default: stdout)."),
) -> None:
    """Write a workflow definition as JSON."""
    workflow = _load_workflow(_workspace(), workflow_id)
    text = dump_workflow(workflow)
    if output:
        output.write_text(text, encoding="utf-8")
        typer.echo(f"Wrote {output}")
    else:
        typer.echo(text, nl=False)


@app.command()
def validate(workflow_id: str) -> None:
    """Validate a workflow against the project's node catalogue."""
    workspace = _workspace()
    registry = _load_registry(workspace)
    report = validate_workflow(_load_workflow(workspace, workflow_id), registry.catalog())
    for issue in report.issues:
        typer.echo(f"{issue.severity.upper():8} {issue.code}: {issue.message}")
    if report.valid:
        typer.echo(f"Workflow '{workflow_id}' is valid. Execution order: "
                   + " -> ".join(report.order))
    else:
        raise typer.Exit(1)


# ------------------------------------------------------------------------------ execution


def _print_event(event) -> None:
    if event.kind == "node_started":
        typer.echo(f"  ▶ {event.node_id}")
    elif event.kind == "node_finished":
        line = f"  {'✓' if event.status == 'SUCCEEDED' else '✗'} {event.node_id} {event.status}"
        if event.message:
            line += f" — {event.message}"
        typer.echo(line)


@app.command()
def run(
    workflow_id: str,
    seed: int | None = typer.Option(None, help="Run seed (default: project default_seed)."),
    no_cache: bool = typer.Option(False, "--no-cache", help="Force fresh execution of all nodes."),
) -> None:
    """Execute a workflow and record the run."""
    from neuroweave.runtime.executor import run_workflow

    workspace = _workspace()
    registry = _load_registry(workspace)
    workflow = _load_workflow(workspace, workflow_id)
    report = validate_workflow(workflow, registry.catalog())
    if not report.valid:
        for issue in report.errors:
            typer.echo(f"ERROR {issue.code}: {issue.message}", err=True)
        _fail("Workflow is invalid; nothing was executed.")
    result = run_workflow(workspace, workflow, registry, seed=seed, use_cache=not no_cache,
                          on_event=_print_event)
    hits = sum(1 for e in workspace.db.node_executions(result.id) if e.cache_hit)
    typer.echo(f"Run {result.id}: {result.status}"
               + (f" ({hits} node(s) reused from cache)" if hits else ""))
    if result.error:
        typer.echo(result.error, err=True)
    if result.status != "SUCCEEDED":
        raise typer.Exit(1)


@app.command()
def runs(
    workflow: str | None = typer.Option(None, "--workflow", "-w"),
    limit: int = typer.Option(20, min=1),
) -> None:
    """List recorded runs, newest first."""
    workspace = _workspace()
    records = workspace.db.list_runs(workflow_id=workflow, limit=limit)
    if not records:
        typer.echo("No runs recorded.")
        return
    _table(["run", "workflow", "status", "trigger", "seed", "created", "snapshot"],
           [[r.id, r.workflow_id, r.status, r.trigger, r.seed, r.created_at[:19],
             _short(r.snapshot_hash)] for r in records])


@app.command()
def show(run_id: str) -> None:
    """Show a run: node executions, outputs, metrics and environment."""
    workspace = _workspace()
    record = _get_run(workspace, run_id)
    typer.echo(f"Run {record.id}  [{record.status}]")
    typer.echo(f"  workflow   {record.workflow_id} ({record.workflow_name})")
    typer.echo(f"  snapshot   {record.snapshot_hash}")
    typer.echo(f"  seed       {record.seed}   cache {'on' if record.use_cache else 'off'}"
               f"   trigger {record.trigger}")
    typer.echo(f"  started    {record.started_at}   finished {record.finished_at}")
    if record.reproduces_run_id:
        typer.echo(f"  reproduces {record.reproduces_run_id}")
    env = record.environment or {}
    if env:
        git = env.get("git") or {}
        system = env.get("platform", {})
        dirty = " (dirty)" if git.get("dirty") else ""
        typer.echo(f"  python     {env.get('python', {}).get('version')}   platform "
                   f"{system.get('system')} {system.get('machine')}"
                   f"   git {_short(git.get('commit'), 10)}{dirty}")
    if record.error:
        typer.echo(f"  error      {record.error}")
    typer.echo("")
    rows = []
    for execution in workspace.db.node_executions(record.id):
        outputs = ", ".join(f"{a.port}={a.id}" for a in workspace.db.outputs_of(execution.id))
        rows.append([execution.node_id, execution.status,
                     "hit" if execution.cache_hit else "", execution.duration_ms,
                     outputs or execution.error])
    _table(["node", "status", "cache", "ms", "outputs / error"], rows)
    metrics = workspace.db.metrics_for_run(record.id)
    if metrics:
        typer.echo("")
        _table(["node", "metric", "value", "direction"],
               [[m.node_id, m.name, m.value, m.direction] for m in metrics])


@app.command()
def logs(run_id: str, node_id: str) -> None:
    """Print the captured output of one node execution."""
    workspace = _workspace()
    _get_run(workspace, run_id)
    execution = next((e for e in workspace.db.node_executions(run_id) if e.node_id == node_id),
                     None)
    if execution is None:
        _fail(f"Run '{run_id}' has no node '{node_id}'.")
    if not execution.log_path:
        typer.echo("(node did not start; no log)")
        return
    path = workspace.dir / execution.log_path
    typer.echo(path.read_text(encoding="utf-8") if path.exists() else "(empty log)", nl=False)


# ------------------------------------------------------------------------------ artifacts


@app.command()
def artifacts(
    run_id: str | None = typer.Option(None, "--run", "-r"),
    kind: str | None = typer.Option(None),
    limit: int = typer.Option(50, min=1),
) -> None:
    """List artifacts."""
    workspace = _workspace()
    records = workspace.db.list_artifacts(run_id=run_id, kind=kind, limit=limit)
    if not records:
        typer.echo("No artifacts recorded.")
        return
    _table(["artifact", "kind", "role", "producer", "size", "sha256"],
           [[a.id, a.kind, a.role, a.source_uri if a.role == "input" else f"{a.node_id}.{a.port}",
             a.size, _short(a.content_hash)] for a in records])


@app.command()
def artifact(
    artifact_id: str,
    output: Path | None = typer.Option(None, "--output", "-o",
                                       help="Write the artifact bytes to this file."),
) -> None:
    """Show artifact metadata, or export its content with --output."""
    workspace = _workspace()
    record = workspace.db.get_artifact(artifact_id)
    if record is None:
        _fail(f"Artifact '{artifact_id}' does not exist.")
    if output:
        if not record.stored:
            _fail("This input was recorded by hash only (larger than max_input_snapshot_bytes).")
        output.write_bytes(workspace.artifacts.get_bytes(record.content_hash))
        typer.echo(f"Wrote {record.size} bytes to {output}")
        return
    typer.echo(json.dumps(record.model_dump(mode="json"), indent=2))


@app.command()
def verify(
    artifact_id: str | None = typer.Argument(None),
    all_: bool = typer.Option(False, "--all", help="Verify every stored artifact."),
) -> None:
    """Re-hash stored artifact bytes and compare with recorded hashes."""
    workspace = _workspace()
    if artifact_id:
        record = workspace.db.get_artifact(artifact_id)
        if record is None:
            _fail(f"Artifact '{artifact_id}' does not exist.")
        records = [record]
    elif all_:
        records = workspace.db.list_artifacts(limit=1_000_000)
    else:
        _fail("Give an artifact id or --all.")
    bad = 0
    checked: set[str] = set()
    for record in records:
        if not record.stored or record.content_hash in checked:
            continue
        checked.add(record.content_hash)
        if not workspace.artifacts.verify(record.content_hash):
            bad += 1
            typer.echo(f"CORRUPT  {record.id} ({record.content_hash})")
    typer.echo(f"Verified {len(checked)} stored object(s): {len(checked) - bad} ok, {bad} corrupt.")
    if bad:
        raise typer.Exit(1)


@app.command()
def lineage(
    artifact_id: str,
    downstream: bool = typer.Option(False, help="Show what was derived from the artifact."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Trace the provenance of an artifact."""
    from neuroweave.provenance import downstream_lineage, upstream_lineage

    workspace = _workspace()
    try:
        graph = (downstream_lineage if downstream else upstream_lineage)(workspace, artifact_id)
    except KeyError as exc:
        _fail(str(exc).strip("'\""))
    if as_json:
        typer.echo(graph.model_dump_json(indent=2))
        return
    labels = {n.id: f"{n.label} [{n.type} {n.id}]" for n in graph.nodes}
    for edge in graph.edges:
        typer.echo(f"{labels.get(edge.source, edge.source)} --{edge.relation}"
                   f"{'' if edge.basis == 'observed' else ' (inferred)'}--> "
                   f"{labels.get(edge.target, edge.target)}")
    if graph.truncated:
        typer.echo("(lineage truncated)")


# ------------------------------------------------------------------------------ experiments


@app.command()
def compare(run_a: str, run_b: str, as_json: bool = typer.Option(False, "--json")) -> None:
    """Compare two runs: snapshot, parameters, inputs, code, outputs, metrics, environment."""
    from neuroweave.experiments import compare_runs

    workspace = _workspace()
    _get_run(workspace, run_a)
    _get_run(workspace, run_b)
    result = compare_runs(workspace, run_a, run_b)
    if as_json:
        typer.echo(result.model_dump_json(indent=2))
        return
    for line in result.summary:
        typer.echo(f"• {line}")
    for node_cmp in result.nodes:
        for key, (a, b) in node_cmp.param_changes.items():
            typer.echo(f"  {node_cmp.node_id}.{key}: {a!r} -> {b!r}")
    if result.metrics:
        typer.echo("")
        _table(["node", "metric", "A", "B", "delta", "direction"],
               [[m.node_id, m.name, m.a, m.b, None if m.delta is None else round(m.delta, 6),
                 m.direction] for m in result.metrics])


@app.command()
def reproduce(run_id: str) -> None:
    """Re-execute a run's snapshot (same seed, no cache) and check outputs are identical."""
    from neuroweave.experiments import reproduce_run

    workspace = _workspace()
    _get_run(workspace, run_id)
    registry = _load_registry(workspace)
    report = reproduce_run(workspace, run_id, registry, on_event=_print_event)
    typer.echo(f"Policy: {report.policy}")
    for check in report.outputs:
        mark = "identical" if check.identical else "DIFFERENT"
        typer.echo(f"  {check.node_id}.{check.port}: {mark}")
    for note in report.notes:
        typer.echo(f"Note: {note}")
    typer.echo(f"Verdict: {report.verdict} (reproduction run {report.reproduction_run_id})")
    if report.verdict != "reproduced":
        raise typer.Exit(1)


# ------------------------------------------------------------------------------ studio


@app.command()
def studio(
    host: str = typer.Option("127.0.0.1", help="Interface to bind (keep local)."),
    port: int = typer.Option(8765),
    open_browser: bool = typer.Option(True, "--open/--no-open"),
) -> None:
    """Start NeuroWeave Studio for this project."""
    import uvicorn

    from neuroweave.server.app import STATIC_DIR, create_app

    workspace = _workspace()
    if host not in ("127.0.0.1", "localhost", "::1"):
        typer.echo("Warning: the Studio API has no authentication and executes project code. "
                   "Binding to a non-loopback interface exposes it to your network.", err=True)
    if not (STATIC_DIR / "index.html").exists():
        typer.echo("Studio UI is not built; the API is available but the web UI is not. "
                   "Build it with `npm --prefix apps/studio install && npm --prefix apps/studio "
                   "run build`.", err=True)
    if not _confirm_trust(workspace):
        typer.echo("Opening without importing node code: workflows and run history can be "
                   "browsed, but the node catalogue is empty and runs are refused until you "
                   "run `nw trust`.", err=True)
    url = f"http://{host}:{port}"
    typer.echo(f"NeuroWeave Studio for {workspace.root} at {url}")
    typer.echo("Node code runs with your user permissions (no sandbox). Press Ctrl+C to stop.")
    if open_browser:
        import threading
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(workspace.root, allowed_hosts_extra=[host]), host=host, port=port,
                log_level="warning")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
