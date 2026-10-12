from __future__ import annotations

import os

from neuroweave import node
from neuroweave.experiments import compare_runs, reproduce_run, reproduction_report
from neuroweave.kernel import Edge, NodeInstance, Workflow
from neuroweave.provenance import downstream_lineage, upstream_lineage
from neuroweave.runtime import run_workflow
from neuroweave.runtime.executor import execute_run, prepare_run


def test_pending_reproduction_does_not_report_spurious_differences(
        demo_project, demo_registry) -> None:
    workflow = demo_project.load_workflow("rainfall-yield")
    original = run_workflow(demo_project, workflow, demo_registry)
    pending = prepare_run(demo_project, workflow, seed=original.seed, use_cache=False,
                          trigger="reproduce", reproduces_run_id=original.id)
    report = reproduction_report(demo_project, pending.id)
    assert report.verdict == "pending"
    assert report.code_changed_nodes == []
    assert report.environment_differences == {}
    assert any("not finished" in note for note in report.notes)


def report_artifact(ws, run):
    return next(a for a in ws.db.list_artifacts(run_id=run.id) if a.node_id == "report")


def test_upstream_lineage_reaches_input_file(demo_project, demo_registry) -> None:
    run = run_workflow(demo_project, demo_project.load_workflow("rainfall-yield"), demo_registry)
    assert run.status == "SUCCEEDED", run.error
    lineage = upstream_lineage(demo_project, report_artifact(demo_project, run).id)
    executions = {n.label for n in lineage.nodes if n.type == "execution"}
    assert executions == {"load", "validate", "transform", "statistics", "bootstrap", "plot",
                          "report"}
    inputs = [n for n in lineage.nodes if n.type == "artifact" and n.data["role"] == "input"]
    assert [n.label for n in inputs] == ["data/field_trial.csv"]
    assert all(e.basis == "observed" for e in lineage.edges)
    relations = {(e.relation) for e in lineage.edges}
    assert relations == {"used", "wasGeneratedBy"}


def test_downstream_lineage_and_inferred_twins(demo_project, demo_registry) -> None:
    workflow = demo_project.load_workflow("rainfall-yield")
    first = run_workflow(demo_project, workflow, demo_registry)
    second = run_workflow(demo_project, workflow, demo_registry, use_cache=False)
    csv_first = next(a for a in demo_project.db.list_artifacts(run_id=first.id, role="input"))
    lineage = downstream_lineage(demo_project, csv_first.id)
    labels = {n.label for n in lineage.nodes if n.type == "execution"}
    assert "report" in labels
    inferred = [e for e in lineage.edges if e.basis == "inferred"]
    assert inferred and all(e.relation == "sameContentAs" for e in inferred)
    twin_ids = {e.target for e in inferred}
    second_csv = next(a for a in demo_project.db.list_artifacts(run_id=second.id, role="input"))
    assert second_csv.id in twin_ids


def test_cache_hit_lineage_points_to_original_execution(demo_project, demo_registry) -> None:
    workflow = demo_project.load_workflow("rainfall-yield")
    first = run_workflow(demo_project, workflow, demo_registry)
    second = run_workflow(demo_project, workflow, demo_registry)
    lineage = upstream_lineage(demo_project, report_artifact(demo_project, second).id)
    reuse = [e for e in lineage.edges if e.relation == "reusedResultOf"]
    original_ids = {e.id for e in demo_project.db.node_executions(first.id)}
    assert reuse and {e.source for e in reuse} <= original_ids


def test_compare_reports_parameter_and_metric_changes(demo_project, demo_registry) -> None:
    workflow = demo_project.load_workflow("rainfall-yield")
    first = run_workflow(demo_project, workflow, demo_registry)
    workflow.node("bootstrap").params["resamples"] = 200
    second = run_workflow(demo_project, workflow, demo_registry)
    result = compare_runs(demo_project, first.id, second.id)
    assert not result.same_snapshot
    assert result.workflow_diff.nodes_changed[0].param_changes == {"resamples": (500, 200)}
    bootstrap = next(n for n in result.nodes if n.node_id == "bootstrap")
    assert bootstrap.param_changes == {"resamples": (500, 200)}
    assert bootstrap.cache_hit == (False, False)
    statistics = next(n for n in result.nodes if n.node_id == "statistics")
    assert statistics.cache_hit == (False, True)
    assert all(o.identical for o in statistics.outputs.values())
    width = next(m for m in result.metrics if m.name == "slope_ci_width")
    assert width.direction == "minimize" and width.delta is not None
    assert any("Parameters changed in: bootstrap" in line for line in result.summary)


def test_reproduce_deterministic_example(demo_project, demo_registry) -> None:
    run = run_workflow(demo_project, demo_project.load_workflow("rainfall-yield"), demo_registry)
    report = reproduce_run(demo_project, run.id, demo_registry)
    assert report.verdict == "reproduced", report
    assert len(report.outputs) == 7 and all(c.identical for c in report.outputs)
    reproduction = demo_project.db.get_run(report.reproduction_run_id)
    assert reproduction.reproduces_run_id == run.id and not reproduction.use_cache
    assert not any(e.cache_hit for e in demo_project.db.node_executions(reproduction.id))
    assert report.environment_match == "identical"
    assert report.isolated is False
    assert any("environment lock matches" in note for note in report.notes)


def test_reproduction_environment_match_unknown_without_lock(demo_project, demo_registry) -> None:
    workflow = demo_project.load_workflow("rainfall-yield")
    original = run_workflow(demo_project, workflow, demo_registry)
    # Simulate a run recorded before locks existed.
    demo_project.db.update_run(original.id, environment={
        "python": original.environment["python"],
        "packages": original.environment["packages"],
    })
    report = reproduce_run(demo_project, original.id, demo_registry)
    assert report.verdict == "reproduced"
    assert report.environment_match == "unknown"
    assert any("no environment lock" in note for note in report.notes)


def test_reproduction_isolated_flag_from_trigger(demo_project, demo_registry) -> None:
    workflow = demo_project.load_workflow("rainfall-yield")
    original = run_workflow(demo_project, workflow, demo_registry)
    pending = prepare_run(demo_project, workflow, seed=original.seed, use_cache=False,
                          trigger="reproduce-isolated", reproduces_run_id=original.id)
    execute_run(demo_project, pending.id, demo_registry)
    report = reproduction_report(demo_project, pending.id)
    assert report.verdict == "reproduced"
    assert report.isolated is True
    assert report.environment_match == "identical"
    assert any("rebuilt environment" in note for note in report.notes)


def test_reproduce_detects_nondeterminism(workspace, registry) -> None:
    @node(registry=registry, cache=False)
    def entropy() -> str:
        return os.urandom(8).hex()

    @node(registry=registry)
    def echo(value: str) -> str:
        return value

    wf = Workflow(id="wf", name="wf", nodes=[
        NodeInstance(id="entropy", type=entropy.__neuroweave_node__.id),
        NodeInstance(id="echo", type=echo.__neuroweave_node__.id)],
        edges=[Edge(source="entropy", source_port="output", target="echo",
                    target_port="value")])
    run = run_workflow(workspace, wf, registry)
    report = reproduce_run(workspace, run.id, registry)
    assert report.verdict == "not_reproduced"
    assert {c.node_id for c in report.outputs if not c.identical} == {"entropy", "echo"}
