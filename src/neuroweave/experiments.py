"""Run comparison and explicit reproducibility checks.

Comparisons report structural and recorded differences. They never conclude that a run is
"better": metric directions are displayed as declared by the node author.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from neuroweave.kernel.diff import WorkflowDiff, diff_workflows
from neuroweave.runtime.executor import EventHandler, run_workflow
from neuroweave.sdk.registry import NodeRegistry
from neuroweave.store.db import ArtifactRecord, NodeExecutionRecord, RunRecord
from neuroweave.store.workspace import Workspace

REPRODUCTION_POLICY = (
    "exact-content-hash: every output artifact of every node in the original run must be "
    "byte-identical (equal SHA-256) in the re-execution."
)


class OutputComparison(BaseModel):
    a: str | None
    b: str | None
    identical: bool


class NodeComparison(BaseModel):
    node_id: str
    in_a: bool
    in_b: bool
    status: tuple[str | None, str | None]
    definition: tuple[str | None, str | None]
    version: tuple[str | None, str | None]
    code_changed: bool
    param_changes: dict[str, tuple[Any, Any]] = Field(default_factory=dict)
    input_changes: dict[str, tuple[str | None, str | None]] = Field(default_factory=dict)
    outputs: dict[str, OutputComparison] = Field(default_factory=dict)
    cache_hit: tuple[bool | None, bool | None]
    duration_ms: tuple[float | None, float | None]


class MetricComparison(BaseModel):
    node_id: str
    name: str
    a: float | None
    b: float | None
    delta: float | None
    direction: str | None


class RunComparison(BaseModel):
    run_a: RunRecord
    run_b: RunRecord
    same_snapshot: bool
    workflow_diff: WorkflowDiff
    seed: tuple[int, int]
    nodes: list[NodeComparison]
    metrics: list[MetricComparison]
    environment: dict[str, Any]
    summary: list[str]


def _input_hashes(workspace: Workspace, execution: NodeExecutionRecord) -> dict[str, str]:
    result = {}
    for record in workspace.db.inputs_of(execution.id):
        artifact = workspace.db.get_artifact(record.artifact_id)
        if artifact is not None:
            result[record.port] = artifact.content_hash
    return result


def _outputs(workspace: Workspace, execution: NodeExecutionRecord) -> dict[str, ArtifactRecord]:
    return {a.port or "": a for a in workspace.db.outputs_of(execution.id)}


def _environment_diff(a: dict | None, b: dict | None) -> dict[str, Any]:
    a, b = a or {}, b or {}
    diff: dict[str, Any] = {}
    for section in ("python", "platform", "git", "neuroweave"):
        if a.get(section) != b.get(section):
            diff[section] = {"a": a.get(section), "b": b.get(section)}
    pa, pb = a.get("packages", {}), b.get("packages", {})
    changed = {k: (pa[k], pb[k]) for k in sorted(pa.keys() & pb.keys()) if pa[k] != pb[k]}
    added = {k: pb[k] for k in sorted(pb.keys() - pa.keys())}
    removed = {k: pa[k] for k in sorted(pa.keys() - pb.keys())}
    if changed or added or removed:
        diff["packages"] = {"changed": changed, "added": added, "removed": removed}
    return diff


_MetricKey = tuple[str, str]


def _last_metrics(workspace: Workspace, run_id: str) -> dict[_MetricKey, tuple[float, str | None]]:
    """Final value of each (node, metric) pair; earlier steps are superseded."""
    result: dict[_MetricKey, tuple[float, str | None]] = {}
    for metric in workspace.db.metrics_for_run(run_id):
        result[(metric.node_id, metric.name)] = (metric.value, metric.direction)
    return result


def compare_runs(workspace: Workspace, run_a_id: str, run_b_id: str) -> RunComparison:
    db = workspace.db
    run_a, run_b = db.get_run(run_a_id), db.get_run(run_b_id)
    if run_a is None or run_b is None:
        missing = run_a_id if run_a is None else run_b_id
        raise KeyError(f"Run '{missing}' does not exist.")
    workflow_diff = diff_workflows(workspace.load_snapshot(run_a.snapshot_hash),
                                   workspace.load_snapshot(run_b.snapshot_hash))
    ex_a = {e.node_id: e for e in db.node_executions(run_a.id)}
    ex_b = {e.node_id: e for e in db.node_executions(run_b.id)}

    nodes: list[NodeComparison] = []
    for node_id in sorted(ex_a.keys() | ex_b.keys(),
                          key=lambda n: (ex_a.get(n) or ex_b[n]).ordinal):
        a, b = ex_a.get(node_id), ex_b.get(node_id)
        comparison = NodeComparison(
            node_id=node_id, in_a=a is not None, in_b=b is not None,
            status=(a and a.status, b and b.status),
            definition=(a and a.definition_id, b and b.definition_id),
            version=(a and a.definition_version, b and b.definition_version),
            code_changed=bool(a and b and a.code_hash != b.code_hash),
            cache_hit=(a and a.cache_hit, b and b.cache_hit),
            duration_ms=(a and a.duration_ms, b and b.duration_ms),
        )
        if a and b:
            for key in sorted(a.params.keys() | b.params.keys()):
                if a.params.get(key) != b.params.get(key):
                    comparison.param_changes[key] = (a.params.get(key), b.params.get(key))
            ia, ib = _input_hashes(workspace, a), _input_hashes(workspace, b)
            for port in sorted(ia.keys() | ib.keys()):
                if ia.get(port) != ib.get(port):
                    comparison.input_changes[port] = (ia.get(port), ib.get(port))
        oa = _outputs(workspace, a) if a else {}
        ob = _outputs(workspace, b) if b else {}
        for port in sorted(oa.keys() | ob.keys()):
            ha = oa[port].content_hash if port in oa else None
            hb = ob[port].content_hash if port in ob else None
            comparison.outputs[port] = OutputComparison(a=ha, b=hb,
                                                        identical=ha is not None and ha == hb)
        nodes.append(comparison)

    ma, mb = _last_metrics(workspace, run_a.id), _last_metrics(workspace, run_b.id)
    metrics = []
    for key in sorted(ma.keys() | mb.keys()):
        va = ma[key][0] if key in ma else None
        vb = mb[key][0] if key in mb else None
        direction = (ma.get(key) or mb.get(key) or (0, None))[1]
        metrics.append(MetricComparison(
            node_id=key[0], name=key[1], a=va, b=vb,
            delta=(vb - va) if va is not None and vb is not None else None,
            direction=direction,
        ))

    summary: list[str] = []
    if run_a.snapshot_hash == run_b.snapshot_hash:
        summary.append("Both runs executed the same workflow snapshot.")
    else:
        summary.append("The runs executed different workflow snapshots.")
    if run_a.seed != run_b.seed:
        summary.append(f"Seeds differ ({run_a.seed} vs {run_b.seed}).")
    changed_params = [n.node_id for n in nodes if n.param_changes]
    if changed_params:
        summary.append("Parameters changed in: " + ", ".join(changed_params) + ".")
    changed_code = [n.node_id for n in nodes if n.code_changed]
    if changed_code:
        summary.append("Node source code changed in: " + ", ".join(changed_code) + ".")
    changed_inputs = [n.node_id for n in nodes if n.input_changes]
    if changed_inputs:
        summary.append("Inputs differ for: " + ", ".join(changed_inputs) + ".")
    differing = [n.node_id for n in nodes if any(not o.identical for o in n.outputs.values())]
    if differing:
        summary.append("Outputs differ for: " + ", ".join(differing) + ".")
    elif nodes:
        summary.append("All recorded outputs are byte-identical.")
    environment = _environment_diff(run_a.environment, run_b.environment)
    if environment:
        summary.append("Environment differs in: " + ", ".join(sorted(environment)) + ".")

    return RunComparison(
        run_a=run_a, run_b=run_b, same_snapshot=run_a.snapshot_hash == run_b.snapshot_hash,
        workflow_diff=workflow_diff, seed=(run_a.seed, run_b.seed), nodes=nodes,
        metrics=metrics, environment=environment, summary=summary,
    )


class OutputCheck(BaseModel):
    node_id: str
    port: str
    original: str | None
    reproduced: str | None
    identical: bool


class ReproductionReport(BaseModel):
    original_run_id: str
    reproduction_run_id: str
    policy: str = REPRODUCTION_POLICY
    verdict: Literal["reproduced", "not_reproduced", "failed", "pending"]
    outputs: list[OutputCheck]
    code_changed_nodes: list[str]
    environment_differences: dict[str, Any]
    notes: list[str]


def reproduction_report(workspace: Workspace, reproduction_run_id: str) -> ReproductionReport:
    db = workspace.db
    run = db.get_run(reproduction_run_id)
    if run is None or run.reproduces_run_id is None:
        raise KeyError(f"Run '{reproduction_run_id}' is not a reproduction run.")
    original = db.get_run(run.reproduces_run_id)
    assert original is not None
    comparison = compare_runs(workspace, original.id, run.id)
    checks = [
        OutputCheck(node_id=n.node_id, port=port, original=o.a, reproduced=o.b,
                    identical=o.identical)
        for n in comparison.nodes for port, o in n.outputs.items() if o.a is not None
    ]
    code_changed = [n.node_id for n in comparison.nodes
                    if n.code_changed or n.version[0] != n.version[1]]
    notes: list[str] = []
    if original.status != "SUCCEEDED":
        notes.append(f"The original run ended {original.status}; only its recorded outputs "
                     "are compared.")
    if code_changed:
        notes.append("Node code or version differs from the original run for: "
                     + ", ".join(code_changed) + ". The reproduction used the current code, so "
                     "differences may reflect code changes rather than nondeterminism.")
    if any(n.input_changes for n in comparison.nodes):
        notes.append("Some external inputs changed since the original run.")
    if comparison.environment:
        notes.append("The runtime environment differs: " + ", ".join(comparison.environment)
                     + ".")

    if run.status in ("PENDING", "RUNNING"):
        verdict = "pending"
    elif run.status != "SUCCEEDED":
        verdict = "failed"
    elif checks and all(c.identical for c in checks):
        verdict = "reproduced"
    else:
        verdict = "not_reproduced"
    return ReproductionReport(
        original_run_id=original.id, reproduction_run_id=run.id, verdict=verdict,
        outputs=checks, code_changed_nodes=code_changed,
        environment_differences=comparison.environment, notes=notes,
    )


def reproduce_run(
    workspace: Workspace, run_id: str, registry: NodeRegistry | None = None, *,
    on_event: EventHandler | None = None,
) -> ReproductionReport:
    """Re-execute a run's snapshot with the same seed and caching disabled, then compare."""
    original = workspace.db.get_run(run_id)
    if original is None:
        raise KeyError(f"Run '{run_id}' does not exist.")
    workflow = workspace.load_snapshot(original.snapshot_hash)
    reproduction = run_workflow(workspace, workflow, registry, seed=original.seed,
                                use_cache=False, trigger="reproduce",
                                reproduces_run_id=original.id, on_event=on_event)
    return reproduction_report(workspace, reproduction.id)
