from __future__ import annotations

import random
from pathlib import Path

from neuroweave import log_metric, node
from neuroweave.kernel import Edge, NodeInstance, Workflow
from neuroweave.runtime import load_artifact_value, run_workflow
from neuroweave.sdk import NodeRegistry
from neuroweave.store.workspace import Workspace


def chain(registry: NodeRegistry, *specs, params=None) -> Workflow:
    """specs: (node_id, function, input_port_from_previous or None)."""
    nodes, edges = [], []
    previous = None
    for node_id, func, port in specs:
        nodes.append(NodeInstance(id=node_id, type=func.__neuroweave_node__.id,
                                  params=(params or {}).get(node_id, {})))
        if previous and port:
            edges.append(Edge(source=previous, source_port="output", target=node_id,
                              target_port=port))
        previous = node_id
    return Workflow(id="wf", name="wf", nodes=nodes, edges=edges)


def statuses(ws: Workspace, run_id: str) -> dict[str, str]:
    return {e.node_id: e.status for e in ws.db.node_executions(run_id)}


def test_executes_in_dependency_order_and_records_outputs(workspace, registry) -> None:
    calls: list[str] = []

    @node(registry=registry)
    def make(n: int = 3) -> list[int]:
        calls.append("make")
        print("making", n)
        return list(range(n))

    @node(registry=registry)
    def square(values: list[int]) -> list[int]:
        calls.append("square")
        return [v * v for v in values]

    @node(registry=registry)
    def total(values: list[int]) -> int:
        calls.append("total")
        log_metric("total", sum(values), direction="maximize")
        return sum(values)

    wf = chain(registry, ("make", make, None), ("square", square, "values"),
               ("total", total, "values"), params={"make": {"n": 4}})
    run = run_workflow(workspace, wf, registry)
    assert run.status == "SUCCEEDED", run.error
    assert calls == ["make", "square", "total"]
    executions = workspace.db.node_executions(run.id)
    assert [e.status for e in executions] == ["SUCCEEDED"] * 3
    assert executions[0].params == {"n": 4}
    out = workspace.db.outputs_of(executions[-1].id)[0]
    assert load_artifact_value(workspace, out) == 0 + 1 + 4 + 9
    log = (workspace.dir / executions[0].log_path).read_text()
    assert "making 4" in log
    metrics = workspace.db.metrics_for_run(run.id)
    assert [(m.name, m.value, m.direction) for m in metrics] == [("total", 14.0, "maximize")]
    assert run.environment["python"]["version"]
    assert run.started_at and run.finished_at


def test_failure_propagates_and_downstream_is_skipped(workspace, registry) -> None:
    @node(registry=registry)
    def ok() -> int:
        return 1

    @node(registry=registry)
    def boom(x: int) -> int:
        raise ValueError("bad data")

    @node(registry=registry)
    def after(x: int) -> int:
        raise AssertionError("must not run")

    @node(registry=registry)
    def independent() -> int:
        return 2

    wf = chain(registry, ("ok", ok, None), ("boom", boom, "x"), ("after", after, "x"))
    wf.nodes.append(NodeInstance(id="independent", type=independent.__neuroweave_node__.id))
    run = run_workflow(workspace, wf, registry)
    assert run.status == "FAILED"
    assert "boom" in run.error
    assert statuses(workspace, run.id) == {"ok": "SUCCEEDED", "boom": "FAILED",
                                           "after": "SKIPPED", "independent": "SUCCEEDED"}
    failed = next(e for e in workspace.db.node_executions(run.id) if e.node_id == "boom")
    assert failed.error == "ValueError: bad data" and "Traceback" in failed.traceback
    assert workspace.db.outputs_of(failed.id) == []
    skipped = next(e for e in workspace.db.node_executions(run.id) if e.node_id == "after")
    assert "boom" in skipped.error


def test_runtime_output_type_check(workspace, registry) -> None:
    @node(registry=registry)
    def liar() -> int:
        return "not an int"  # type: ignore[return-value]

    run = run_workflow(workspace, chain(registry, ("liar", liar, None)), registry)
    assert run.status == "FAILED"
    execution = workspace.db.node_executions(run.id)[0]
    assert "expected int" in execution.error


def test_multiple_outputs(workspace, registry) -> None:
    @node(registry=registry, outputs=["low", "high"])
    def split(values: list[int] = [1, 5, 9]) -> tuple[list[int], list[int]]:  # noqa: B006
        return [v for v in values if v < 5], [v for v in values if v >= 5]

    @node(registry=registry)
    def size(values: list[int]) -> int:
        return len(values)

    wf = Workflow(id="wf", name="wf", nodes=[
        NodeInstance(id="split", type=split.__neuroweave_node__.id),
        NodeInstance(id="size", type=size.__neuroweave_node__.id)],
        edges=[Edge(source="split", source_port="high", target="size", target_port="values")])
    run = run_workflow(workspace, wf, registry)
    assert run.status == "SUCCEEDED", run.error
    size_exec = workspace.db.node_executions(run.id)[1]
    assert load_artifact_value(workspace, workspace.db.outputs_of(size_exec.id)[0]) == 2


def test_wrong_multi_output_shape_fails(workspace, registry) -> None:
    @node(registry=registry, outputs=["a", "b"])
    def bad() -> dict:
        return {"a": 1}

    run = run_workflow(workspace, chain(registry, ("bad", bad, None)), registry)
    assert run.status == "FAILED"
    assert "must return keys" in workspace.db.node_executions(run.id)[0].error


def test_downstream_receives_a_copy_not_the_object(workspace, registry) -> None:
    @node(registry=registry)
    def make() -> list[int]:
        return [1, 2]

    @node(registry=registry)
    def mutate(values: list[int]) -> int:
        values.append(99)
        return len(values)

    @node(registry=registry)
    def read(values: list[int]) -> int:
        return len(values)

    wf = Workflow(id="wf", name="wf", nodes=[
        NodeInstance(id="make", type=make.__neuroweave_node__.id),
        NodeInstance(id="mutate", type=mutate.__neuroweave_node__.id),
        NodeInstance(id="read", type=read.__neuroweave_node__.id)],
        edges=[Edge(source="make", source_port="output", target="mutate", target_port="values"),
               Edge(source="make", source_port="output", target="read", target_port="values")])
    run = run_workflow(workspace, wf, registry)
    read_exec = workspace.db.node_executions(run.id)[2]
    assert load_artifact_value(workspace, workspace.db.outputs_of(read_exec.id)[0]) == 2


def test_cancellation_between_nodes(workspace, registry) -> None:
    @node(registry=registry, cache=False)
    def first() -> int:
        from neuroweave import current_context

        workspace.db.request_cancel(current_context().run_id)
        return 1

    @node(registry=registry)
    def second(x: int) -> int:
        return x

    run = run_workflow(workspace, chain(registry, ("first", first, None),
                                        ("second", second, "x")), registry)
    assert run.status == "CANCELLED"
    assert statuses(workspace, run.id) == {"first": "SUCCEEDED", "second": "CANCELLED"}


def test_seeds_are_derived_and_recorded(workspace, registry) -> None:
    @node(registry=registry, cache=False)
    def draw() -> float:
        return random.random()

    wf = chain(registry, ("draw", draw, None))
    a = run_workflow(workspace, wf, registry, seed=7)
    b = run_workflow(workspace, wf, registry, seed=7)
    c = run_workflow(workspace, wf, registry, seed=8)

    def value(run):
        execution = workspace.db.node_executions(run.id)[0]
        return execution.seed, load_artifact_value(workspace,
                                                   workspace.db.outputs_of(execution.id)[0])

    assert value(a) == value(b)
    assert value(a) != value(c)


def test_invalid_workflow_is_not_executed(workspace, registry) -> None:
    wf = Workflow(id="wf", name="wf", nodes=[NodeInstance(id="x", type="missing:node")])
    run = run_workflow(workspace, wf, registry)
    assert run.status == "FAILED"
    assert "validation failed" in run.error
    assert workspace.db.node_executions(run.id) == []


def test_missing_input_file_fails_with_clear_message(workspace, registry) -> None:
    @node(registry=registry)
    def read(path: Path) -> str:
        return path.read_text()

    wf = chain(registry, ("read", read, None), params={"read": {"path": "nope.txt"}})
    run = run_workflow(workspace, wf, registry)
    execution = workspace.db.node_executions(run.id)[0]
    assert execution.status == "FAILED" and "file not found" in execution.error
