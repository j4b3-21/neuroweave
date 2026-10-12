from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from neuroweave import Table, node
from neuroweave.kernel import (
    CycleError,
    Edge,
    NodeInstance,
    Workflow,
    diff_workflows,
    downstream,
    dump_workflow,
    load_workflow,
    snapshot_hash,
    topological_order,
    upstream,
    validate_workflow,
)
from neuroweave.sdk import NodeRegistry


@pytest.fixture
def catalog(registry: NodeRegistry):
    @node(registry=registry)
    def load(path: Path) -> Table:
        return Table.from_csv(path)

    @node(registry=registry)
    def scale(data: Table, factor: float = 1.0) -> Table:
        return data

    @node(registry=registry)
    def count(data: Table) -> int:
        return data.num_rows

    @node(registry=registry)
    def label(text: str) -> str:
        return text

    return {d.name: d for d in registry.definitions()}


def make(catalog, nodes, edges, params=None) -> Workflow:
    params = params or {}
    return Workflow(
        id="wf", name="wf",
        nodes=[NodeInstance(id=i, type=catalog[t].id, params=params.get(i, {}))
               for i, t in nodes],
        edges=[Edge(source=s, source_port=sp, target=t, target_port=tp)
               for s, sp, t, tp in edges],
    )


def codes(report) -> set[str]:
    return {i.code for i in report.issues}


def test_valid_workflow_and_deterministic_order(catalog) -> None:
    wf = make(catalog, [("load", "load"), ("scale", "scale"), ("count", "count")],
              [("load", "output", "scale", "data"), ("scale", "output", "count", "data")],
              {"load": {"path": "x.csv"}, "scale": {"factor": 2}})
    report = validate_workflow(wf, catalog.values())
    assert report.valid, report.issues
    assert report.order == ["load", "scale", "count"]


def test_ties_follow_declaration_order(catalog) -> None:
    wf = make(catalog, [("b", "label"), ("a", "label"), ("c", "label")], [])
    assert topological_order(wf) == ["b", "a", "c"]


def test_rejects_type_mismatch(catalog) -> None:
    wf = make(catalog, [("load", "load"), ("count", "count"), ("label", "label")],
              [("load", "output", "count", "data"), ("count", "output", "label", "text")],
              {"load": {"path": "x.csv"}})
    report = validate_workflow(wf, catalog.values())
    assert not report.valid
    assert "type_mismatch" in codes(report)
    issue = next(i for i in report.issues if i.code == "type_mismatch")
    assert issue.node_id == "label" and "int" in issue.message and "str" in issue.message


@pytest.mark.parametrize(
    ("nodes", "edges", "params", "expected"),
    [
        ([("count", "count")], [], {}, "missing_input"),
        ([("load", "load")], [], {"load": {"path": 3}}, "invalid_param"),
        ([("load", "load")], [], {"load": {"path": "a", "bogus": 1}}, "unknown_param"),
        ([("count", "count")], [], {"count": {"data": {}}}, "param_not_editable"),
        ([("l", "label")], [("l", "output", "l", "text")], {}, "self_loop"),
        ([("load", "load"), ("count", "count")], [("load", "nope", "count", "data")],
         {"load": {"path": "a"}}, "unknown_output"),
        ([("load", "load"), ("count", "count")], [("load", "output", "count", "nope")],
         {"load": {"path": "a"}}, "unknown_input"),
        ([("load", "load"), ("count", "count")], [("load", "output", "ghost", "data")],
         {"load": {"path": "a"}}, "unknown_edge_node"),
        ([("load", "load"), ("scale", "scale")], [("load", "output", "scale", "data")],
         {"load": {"path": "a"}, "scale": {"data": 1}}, "param_and_connection"),
    ],
)
def test_validation_errors(catalog, nodes, edges, params, expected) -> None:
    report = validate_workflow(make(catalog, nodes, edges, params), catalog.values())
    assert not report.valid
    assert expected in codes(report)


def test_multiple_inputs_and_unknown_type(catalog) -> None:
    wf = make(catalog, [("a", "load"), ("b", "load"), ("c", "count")],
              [("a", "output", "c", "data"), ("b", "output", "c", "data")],
              {"a": {"path": "x"}, "b": {"path": "y"}})
    wf.nodes.append(NodeInstance(id="z", type="nowhere:thing"))
    report = validate_workflow(wf, catalog.values())
    assert {"multiple_inputs", "unknown_node_type"} <= codes(report)


def test_cycle_detection(catalog) -> None:
    wf = make(catalog, [("a", "scale"), ("b", "scale")],
              [("a", "output", "b", "data"), ("b", "output", "a", "data")])
    with pytest.raises(CycleError) as info:
        topological_order(wf)
    assert info.value.nodes == ["a", "b"]
    assert "cycle" in codes(validate_workflow(wf, catalog.values()))


def test_upstream_downstream(catalog) -> None:
    wf = make(catalog, [("load", "load"), ("scale", "scale"), ("count", "count")],
              [("load", "output", "scale", "data"), ("scale", "output", "count", "data")])
    assert downstream(wf, ["load"]) == {"scale", "count"}
    assert upstream(wf, ["count"]) == {"load", "scale"}


def test_serialization_round_trip_is_byte_identical(catalog) -> None:
    wf = make(catalog, [("load", "load"), ("scale", "scale")],
              [("load", "output", "scale", "data")], {"scale": {"factor": 0.5}})
    text = dump_workflow(wf)
    assert dump_workflow(load_workflow(text)) == text
    assert snapshot_hash(load_workflow(text)) == snapshot_hash(wf)


def test_snapshot_hash_changes_with_params(catalog) -> None:
    a = make(catalog, [("scale", "scale")], [], {"scale": {"factor": 1.0}})
    b = make(catalog, [("scale", "scale")], [], {"scale": {"factor": 2.0}})
    assert snapshot_hash(a) != snapshot_hash(b)


def test_rejects_malformed_and_future_documents() -> None:
    with pytest.raises(ValidationError):
        Workflow.model_validate({"id": "Bad Id", "name": "x"})
    with pytest.raises(ValidationError):
        Workflow.model_validate({"id": "ok", "name": "x", "nodes": [{"id": "n", "type": "t",
                                                                     "extra": 1}]})
    with pytest.raises(ValueError, match="schema_version"):
        load_workflow('{"schema_version": 99, "id": "x", "name": "x"}')


def test_diff_ignores_layout(catalog) -> None:
    a = make(catalog, [("scale", "scale")], [], {"scale": {"factor": 1.0}})
    b = a.model_copy(deep=True)
    b.nodes[0].position.x = 500
    assert diff_workflows(a, b).identical
    b.nodes[0].params["factor"] = 3.0
    b.nodes.append(NodeInstance(id="extra", type=catalog["count"].id))
    diff = diff_workflows(a, b)
    assert diff.nodes_added == ["extra"]
    assert diff.nodes_changed[0].param_changes == {"factor": (1.0, 3.0)}
