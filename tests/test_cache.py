from __future__ import annotations

from pathlib import Path

from neuroweave import node
from neuroweave.kernel import Edge, NodeInstance, Workflow
from neuroweave.runtime import run_workflow
from neuroweave.runtime.cache import cache_key
from neuroweave.sdk import NodeRegistry


def build(registry: NodeRegistry, calls: list[str], *, cache_last: bool = True):
    @node(registry=registry)
    def read(path: Path) -> str:
        calls.append("read")
        return path.read_text()

    @node(registry=registry)
    def upper(text: str, repeat: int = 1) -> str:
        calls.append("upper")
        return text.upper() * repeat

    @node(registry=registry, cache=cache_last)
    def length(text: str) -> int:
        calls.append("length")
        return len(text)

    def workflow(repeat: int = 1) -> Workflow:
        return Workflow(id="wf", name="wf", nodes=[
            NodeInstance(id="read", type=read.__neuroweave_node__.id,
                         params={"path": "input.txt"}),
            NodeInstance(id="upper", type=upper.__neuroweave_node__.id,
                         params={"repeat": repeat}),
            NodeInstance(id="length", type=length.__neuroweave_node__.id)],
            edges=[Edge(source="read", source_port="output", target="upper", target_port="text"),
                   Edge(source="upper", source_port="output", target="length",
                        target_port="text")])

    return workflow


def hits(ws, run) -> dict[str, bool]:
    return {e.node_id: e.cache_hit for e in ws.db.node_executions(run.id)}


def test_second_run_reuses_everything(workspace, registry) -> None:
    (workspace.root / "input.txt").write_text("abc")
    calls: list[str] = []
    workflow = build(registry, calls)
    first = run_workflow(workspace, workflow(), registry)
    second = run_workflow(workspace, workflow(), registry)
    assert calls == ["read", "upper", "length"]
    assert hits(workspace, second) == {"read": True, "upper": True, "length": True}
    reused = workspace.db.node_executions(second.id)[0]
    original = workspace.db.node_executions(first.id)[0]
    assert reused.cache_source_id == original.id
    out = workspace.db.outputs_of(reused.id)[0]
    assert out.reused_from == workspace.db.outputs_of(original.id)[0].id
    assert "Reused cached result" in (workspace.dir / reused.log_path).read_text()


def test_parameter_change_reruns_only_affected_subgraph(workspace, registry) -> None:
    (workspace.root / "input.txt").write_text("abc")
    calls: list[str] = []
    workflow = build(registry, calls)
    run_workflow(workspace, workflow(1), registry)
    calls.clear()
    second = run_workflow(workspace, workflow(2), registry)
    assert calls == ["upper", "length"]
    assert hits(workspace, second) == {"read": True, "upper": False, "length": False}


def test_input_file_change_invalidates_everything_downstream(workspace, registry) -> None:
    source = workspace.root / "input.txt"
    source.write_text("abc")
    calls: list[str] = []
    workflow = build(registry, calls)
    run_workflow(workspace, workflow(), registry)
    source.write_text("abcd")
    calls.clear()
    run_workflow(workspace, workflow(), registry)
    assert calls == ["read", "upper", "length"]


def test_identical_upstream_output_still_allows_downstream_reuse(workspace, registry) -> None:
    source = workspace.root / "input.txt"
    source.write_text("abc")
    calls: list[str] = []
    workflow = build(registry, calls)
    run_workflow(workspace, workflow(), registry)
    source.write_text("ABC")  # upper() output is identical
    calls.clear()
    run_workflow(workspace, workflow(), registry)
    assert calls == ["read", "upper"]


def test_no_cache_and_cache_false(workspace, registry) -> None:
    (workspace.root / "input.txt").write_text("abc")
    calls: list[str] = []
    workflow = build(registry, calls, cache_last=False)
    run_workflow(workspace, workflow(), registry)
    calls.clear()
    run_workflow(workspace, workflow(), registry)
    assert calls == ["length"]
    calls.clear()
    fresh = run_workflow(workspace, workflow(), registry, use_cache=False)
    assert calls == ["read", "upper", "length"]
    notes = {e.node_id: e.cache_note for e in workspace.db.node_executions(fresh.id)}
    assert notes["read"] == "caching disabled for this run"
    assert "cache=False" in notes["length"]


def test_cache_key_covers_code_version_params_inputs_and_seed(registry) -> None:
    @node(registry=registry)
    def f(x: int) -> int:
        return x

    d = f.__neuroweave_node__
    base, _ = cache_key(d, {"x": 1}, {"data": "json/v1:aa"}, 0)
    variants = [
        cache_key(d.model_copy(update={"version": "2"}), {"x": 1}, {"data": "json/v1:aa"}, 0),
        cache_key(d.model_copy(update={"code_hash": "0" * 64}), {"x": 1},
                  {"data": "json/v1:aa"}, 0),
        cache_key(d, {"x": 2}, {"data": "json/v1:aa"}, 0),
        cache_key(d, {"x": 1}, {"data": "json/v1:bb"}, 0),
        cache_key(d, {"x": 1}, {"data": "json/v1:aa"}, 1),
    ]
    assert base and all(key not in (None, base) for key, _ in variants)
    assert cache_key(d, {"x": 1}, {"data": "json/v1:aa"}, 0)[0] == base
    key, reason = cache_key(d.model_copy(update={"code_hash": None}), {}, {}, 0)
    assert key is None and "source code" in reason


def test_corrupted_cache_entry_is_not_reused(workspace, registry) -> None:
    (workspace.root / "input.txt").write_text("abc")
    calls: list[str] = []
    workflow = build(registry, calls)
    first = run_workflow(workspace, workflow(), registry)
    out = workspace.db.outputs_of(workspace.db.node_executions(first.id)[1].id)[0]
    workspace.artifacts.path_for(out.content_hash).write_bytes(b"garbage")
    calls.clear()
    second = run_workflow(workspace, workflow(), registry)
    assert "upper" in calls
    upper = workspace.db.node_executions(second.id)[1]
    assert not upper.cache_hit and "integrity" in upper.cache_note
    assert workspace.artifacts.verify(out.content_hash)  # rewritten with correct bytes


def test_failed_executions_are_never_cache_sources(workspace, registry) -> None:
    state = {"fail": True}

    @node(registry=registry)
    def flaky() -> int:
        if state["fail"]:
            raise RuntimeError("transient")
        return 1

    wf = Workflow(id="wf", name="wf",
                  nodes=[NodeInstance(id="f", type=flaky.__neuroweave_node__.id)])
    assert run_workflow(workspace, wf, registry).status == "FAILED"
    state["fail"] = False
    second = run_workflow(workspace, wf, registry)
    assert second.status == "SUCCEEDED"
    assert not workspace.db.node_executions(second.id)[0].cache_hit
