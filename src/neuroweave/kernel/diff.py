"""Structural differences between two workflow definitions (layout is ignored)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from neuroweave.kernel.model import Workflow

_MISSING = "<unset>"


class NodeChange(BaseModel):
    node_id: str
    type_change: tuple[str, str] | None = None
    label_change: tuple[str | None, str | None] | None = None
    param_changes: dict[str, tuple[Any, Any]] = Field(default_factory=dict)


class WorkflowDiff(BaseModel):
    identical: bool
    nodes_added: list[str] = Field(default_factory=list)
    nodes_removed: list[str] = Field(default_factory=list)
    nodes_changed: list[NodeChange] = Field(default_factory=list)
    edges_added: list[str] = Field(default_factory=list)
    edges_removed: list[str] = Field(default_factory=list)
    metadata_changes: dict[str, tuple[Any, Any]] = Field(default_factory=dict)


def diff_workflows(before: Workflow, after: Workflow) -> WorkflowDiff:
    a_nodes = {n.id: n for n in before.nodes}
    b_nodes = {n.id: n for n in after.nodes}
    changed: list[NodeChange] = []
    for node_id in sorted(a_nodes.keys() & b_nodes.keys()):
        a, b = a_nodes[node_id], b_nodes[node_id]
        change = NodeChange(node_id=node_id)
        if a.type != b.type:
            change.type_change = (a.type, b.type)
        if a.label != b.label:
            change.label_change = (a.label, b.label)
        for key in sorted(a.params.keys() | b.params.keys()):
            va, vb = a.params.get(key, _MISSING), b.params.get(key, _MISSING)
            if va != vb:
                change.param_changes[key] = (va, vb)
        if change.type_change or change.label_change or change.param_changes:
            changed.append(change)

    a_edges = {e.key for e in before.edges}
    b_edges = {e.key for e in after.edges}
    metadata = {
        field: (getattr(before, field), getattr(after, field))
        for field in ("name", "description")
        if getattr(before, field) != getattr(after, field)
    }
    result = WorkflowDiff(
        identical=False,
        nodes_added=sorted(b_nodes.keys() - a_nodes.keys()),
        nodes_removed=sorted(a_nodes.keys() - b_nodes.keys()),
        nodes_changed=changed,
        edges_added=sorted(b_edges - a_edges),
        edges_removed=sorted(a_edges - b_edges),
        metadata_changes=metadata,
    )
    result.identical = not (result.nodes_added or result.nodes_removed or result.nodes_changed
                            or result.edges_added or result.edges_removed or metadata)
    return result
