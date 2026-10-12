"""Semantic validation of a workflow against a catalogue of node definitions."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, Field

from neuroweave.kernel.definitions import NodeDefinition
from neuroweave.kernel.model import Edge, Workflow
from neuroweave.kernel.planning import CycleError, topological_order
from neuroweave.kernel.types import compatibility, validate_value


class Issue(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    node_id: str | None = None
    port: str | None = None
    edge: Edge | None = None


class ValidationReport(BaseModel):
    valid: bool
    issues: list[Issue] = Field(default_factory=list)
    order: list[str] = Field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    def summary(self) -> str:
        if self.valid and not self.issues:
            return "valid"
        return "; ".join(i.message for i in self.issues)


def validate_workflow(
    workflow: Workflow, definitions: Iterable[NodeDefinition] | dict[str, NodeDefinition]
) -> ValidationReport:
    catalog = definitions if isinstance(definitions, dict) else {d.id: d for d in definitions}
    issues: list[Issue] = []

    def error(code: str, message: str, **where) -> None:
        issues.append(Issue(severity="error", code=code, message=message, **where))

    def warn(code: str, message: str, **where) -> None:
        issues.append(Issue(severity="warning", code=code, message=message, **where))

    if not workflow.nodes:
        warn("empty_workflow", "Workflow has no nodes.")

    for node_id, count in Counter(n.id for n in workflow.nodes).items():
        if count > 1:
            error("duplicate_node", f"Node id '{node_id}' is used {count} times.", node_id=node_id)

    nodes = {n.id: n for n in workflow.nodes}
    connected: dict[tuple[str, str], list[Edge]] = {}

    seen_edges: set[str] = set()
    for edge in workflow.edges:
        if edge.key in seen_edges:
            error("duplicate_edge", f"Duplicate connection {edge.key}.", edge=edge)
            continue
        seen_edges.add(edge.key)
        source, target = nodes.get(edge.source), nodes.get(edge.target)
        if source is None or target is None:
            missing = edge.source if source is None else edge.target
            error("unknown_edge_node", f"Connection {edge.key} refers to missing node "
                  f"'{missing}'.", edge=edge)
            continue
        if edge.source == edge.target:
            error("self_loop", f"Node '{edge.source}' cannot be connected to itself.", edge=edge)
            continue
        connected.setdefault((edge.target, edge.target_port), []).append(edge)
        source_def, target_def = catalog.get(source.type), catalog.get(target.type)
        if source_def is None or target_def is None:
            continue
        out_port = source_def.output(edge.source_port)
        in_port = target_def.input(edge.target_port)
        if out_port is None:
            error("unknown_output", f"'{source_def.label}' has no output '{edge.source_port}'.",
                  node_id=edge.source, port=edge.source_port, edge=edge)
            continue
        if in_port is None:
            error("unknown_input", f"'{target_def.label}' has no input '{edge.target_port}'.",
                  node_id=edge.target, port=edge.target_port, edge=edge)
            continue
        level, reason = compatibility(out_port.type, in_port.type)
        if level == "error":
            error("type_mismatch", f"Cannot connect {edge.source}.{edge.source_port} "
                  f"({out_port.type}) to {edge.target}.{edge.target_port} ({in_port.type}): "
                  f"{reason}.", node_id=edge.target, port=edge.target_port, edge=edge)
        elif level == "warning":
            warn("type_warning", f"{edge.source}.{edge.source_port} -> "
                 f"{edge.target}.{edge.target_port}: {reason}.", node_id=edge.target,
                 port=edge.target_port, edge=edge)

    for (target, port), edges in connected.items():
        if len(edges) > 1:
            error("multiple_inputs", f"Input '{port}' of '{target}' has {len(edges)} incoming "
                  "connections; an input accepts exactly one.", node_id=target, port=port)

    for instance in workflow.nodes:
        definition = catalog.get(instance.type)
        if definition is None:
            error("unknown_node_type", f"Node '{instance.id}' uses unknown node type "
                  f"'{instance.type}'. Is its module listed in project.json node_modules?",
                  node_id=instance.id)
            continue
        for name, value in instance.params.items():
            port = definition.input(name)
            if port is None:
                error("unknown_param", f"'{instance.id}' has no parameter '{name}'.",
                      node_id=instance.id, port=name)
            elif (instance.id, name) in connected:
                error("param_and_connection", f"Input '{name}' of '{instance.id}' is both "
                      "connected and set as a parameter; remove one.", node_id=instance.id,
                      port=name)
            elif not port.editable:
                error("param_not_editable", f"Input '{name}' of '{instance.id}' has type "
                      f"{port.type} and must be connected, not set as a parameter.",
                      node_id=instance.id, port=name)
            else:
                problem = validate_value(port.type, value)
                if problem:
                    error("invalid_param", f"Parameter '{name}' of '{instance.id}': {problem}.",
                          node_id=instance.id, port=name)
        for port in definition.inputs:
            provided = (instance.id, port.name) in connected or port.name in instance.params
            if port.required and not provided:
                error("missing_input", f"Required input '{port.name}' of '{instance.id}' is "
                      "neither connected nor set.", node_id=instance.id, port=port.name)

    order: list[str] = []
    try:
        order = topological_order(workflow)
    except CycleError as exc:
        error("cycle", str(exc) + ". Workflows must be acyclic.")

    has_errors = any(i.severity == "error" for i in issues)
    return ValidationReport(valid=not has_errors, issues=issues, order=order)
