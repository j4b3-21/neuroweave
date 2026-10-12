from __future__ import annotations

import types
from pathlib import Path
from typing import Literal

import pytest

from neuroweave import Table, node
from neuroweave.sdk import NodeDefinitionError, NodeRegistry, UnknownNodeError, WorkflowBuilder
from neuroweave.sdk.registry import load_node_modules


def test_bare_decorator_returns_original_function(registry: NodeRegistry) -> None:
    @node(registry=registry)
    def double(x: int) -> int:
        """Double a number."""
        return x * 2

    assert double(4) == 8
    definition = double.__neuroweave_node__
    assert definition.id.endswith(":test_bare_decorator_returns_original_function.<locals>."
                                  "double")
    assert definition.description == "Double a number."
    assert definition.label == "Double"
    assert definition.code_hash and len(definition.code_hash) == 64


def test_bare_node_without_parentheses(registry: NodeRegistry) -> None:
    from neuroweave.sdk import node as bare

    def plain(x: int) -> int:
        return x

    decorated = bare(plain)  # same as @node
    assert decorated is plain and decorated(3) == 3


def test_ports_from_signature(registry: NodeRegistry) -> None:
    @node(registry=registry, version=3, category="Stats", tags=["t"])
    def analyse(
        data: Table,
        path: Path,
        mode: Literal["fast", "slow"] = "fast",
        alpha: float = 0.05,
        columns: list[str] | None = None,
        flag=True,
    ) -> dict[str, float]:
        return {}

    d = analyse.__neuroweave_node__
    ports = {p.name: p for p in d.inputs}
    assert d.version == "3" and d.category == "Stats"
    assert ports["data"].required and not ports["data"].editable
    assert ports["path"].widget == "file" and ports["path"].required
    assert ports["mode"].widget == "select" and ports["mode"].choices == ["fast", "slow"]
    assert ports["mode"].default == "fast" and not ports["mode"].required
    assert ports["alpha"].widget == "number"
    assert str(ports["columns"].type) == "list[str] | None"
    assert ports["flag"].widget == "checkbox"  # inferred from default
    assert [p.name for p in d.outputs] == ["output"]
    assert str(d.outputs[0].type) == "dict[str, float]"


def test_multiple_and_no_outputs(registry: NodeRegistry) -> None:
    @node(registry=registry, outputs=["train", "test"])
    def split(data: Table) -> tuple[Table, Table]:
        return data, data

    @node(registry=registry)
    def sink(data: Table) -> None:
        return None

    assert [str(p.type) for p in split.__neuroweave_node__.outputs] == ["Table", "Table"]
    assert sink.__neuroweave_node__.outputs == []


def test_rejects_unsupported_signatures(registry: NodeRegistry) -> None:
    with pytest.raises(NodeDefinitionError):
        @node(registry=registry)
        def varargs(*values):
            return values

    with pytest.raises(NodeDefinitionError):
        @node(registry=registry)
        def positional(x, /):
            return x


def test_same_name_in_different_modules_does_not_collide(registry: NodeRegistry) -> None:
    for module_name in ("lab_a", "lab_b"):
        module = types.ModuleType(module_name)
        module.__dict__["registry"] = registry
        exec("from neuroweave import node\n@node(registry=registry)\ndef load(x: int) -> int:\n"
             "    return x\n", module.__dict__)
    assert {"lab_a:load", "lab_b:load"} <= {d.id for d in registry.definitions()}
    with pytest.raises(UnknownNodeError, match="ambiguous"):
        registry.resolve("load")
    assert registry.resolve("lab_a:load").definition.module == "lab_a"


def test_load_node_modules_reports_errors(tmp_path: Path) -> None:
    (tmp_path / "broken_nodes_mod.py").write_text("raise RuntimeError('boom')\n")
    errors = load_node_modules(["broken_nodes_mod", "missing_mod_xyz"], tmp_path)
    assert {e.module for e in errors} == {"broken_nodes_mod", "missing_mod_xyz"}
    assert "boom" in errors[0].error


def test_builder_creates_edges_and_params(registry: NodeRegistry) -> None:
    @node(registry=registry)
    def source(n: int = 3) -> list[int]:
        return list(range(n))

    @node(registry=registry)
    def total(values: list[int]) -> int:
        return sum(values)

    b = WorkflowBuilder("sum", registry=registry)
    s = b.add(source, n=5)
    b.add(total, values=s)
    workflow = b.build()
    assert [n.id for n in workflow.nodes] == ["source", "total"]
    assert workflow.nodes[0].params == {"n": 5}
    assert workflow.edges[0].key == "source.output->total.values"
    assert workflow.nodes[1].position.x > workflow.nodes[0].position.x
