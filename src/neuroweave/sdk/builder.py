"""Developer-facing construction of workflows from registered node functions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from neuroweave.kernel.definitions import NodeDefinition
from neuroweave.kernel.model import Edge, NodeInstance, Position, Workflow
from neuroweave.kernel.planning import depths
from neuroweave.sdk.registry import NodeRegistry, default_registry


@dataclass(frozen=True)
class OutputRef:
    node_id: str
    port: str


@dataclass(frozen=True)
class NodeRef:
    node_id: str
    definition: NodeDefinition

    def out(self, port: str) -> OutputRef:
        if self.definition.output(port) is None:
            names = [p.name for p in self.definition.outputs]
            raise ValueError(f"'{self.node_id}' has no output '{port}'; outputs are {names}.")
        return OutputRef(self.node_id, port)

    def default_output(self) -> OutputRef:
        if len(self.definition.outputs) != 1:
            names = [p.name for p in self.definition.outputs]
            raise ValueError(f"'{self.node_id}' has outputs {names}; use .out(name) to choose.")
        return OutputRef(self.node_id, self.definition.outputs[0].name)


class WorkflowBuilder:
    """Build a workflow in Python::

        b = WorkflowBuilder("demo", name="Demo")
        raw = b.add(load_dataset, path="data/measurements.csv")
        clean = b.add(validate_dataset, data=raw)
        workflow = b.build()

    Keyword arguments that are ``NodeRef``/``OutputRef`` become edges; all others become
    literal parameters. Validation is not performed here; call ``validate_workflow``.
    """

    def __init__(
        self, workflow_id: str, *, name: str | None = None, description: str = "",
        registry: NodeRegistry | None = None,
    ) -> None:
        self._registry = default_registry if registry is None else registry
        self._workflow = Workflow(id=workflow_id, name=name or workflow_id,
                                  description=description)

    def add(
        self, node: Callable[..., Any] | str, *, id: str | None = None, label: str | None = None,
        **inputs: Any,
    ) -> NodeRef:
        reference = node if isinstance(node, str) else getattr(
            node, "__neuroweave_node__", None
        )
        if reference is None:
            raise TypeError(f"{node!r} is not a registered @node function.")
        definition = self._registry.resolve(
            reference if isinstance(reference, str) else reference.id
        ).definition
        node_id = id or self._unique_id(definition.name)
        params: dict[str, Any] = {}
        for port, value in inputs.items():
            if isinstance(value, NodeRef):
                value = value.default_output()
            if isinstance(value, OutputRef):
                self._workflow.edges.append(
                    Edge(source=value.node_id, source_port=value.port, target=node_id,
                         target_port=port)
                )
            else:
                params[port] = value
        self._workflow.nodes.append(
            NodeInstance(id=node_id, type=definition.id, label=label, params=params)
        )
        return NodeRef(node_id, definition)

    def build(self, *, layout: bool = True) -> Workflow:
        workflow = self._workflow.model_copy(deep=True)
        if layout:
            auto_layout(workflow)
        return workflow

    def _unique_id(self, base: str) -> str:
        existing = {n.id for n in self._workflow.nodes}
        candidate, counter = base, 2
        while candidate in existing:
            candidate, counter = f"{base}_{counter}", counter + 1
        return candidate


def auto_layout(workflow: Workflow, *, dx: float = 320.0, dy: float = 300.0) -> None:
    """Place nodes in columns by dependency depth (no-op for cyclic graphs)."""
    try:
        levels = depths(workflow)
    except ValueError:
        return
    rows: dict[int, int] = {}
    for instance in workflow.nodes:
        depth = levels.get(instance.id, 0)
        row = rows.get(depth, 0)
        rows[depth] = row + 1
        instance.position = Position(x=depth * dx, y=row * dy)
