"""Lineage queries over recorded executions.

Relations follow W3C PROV vocabulary in data-flow direction:

* ``used``             artifact -> node execution  (the execution consumed the artifact)
* ``wasGeneratedBy``   node execution -> artifact  (the execution produced the artifact)
* ``reusedResultOf``   original execution -> cache-hit execution
* ``sameContentAs``    artifact -- artifact with identical bytes but no recorded link

The first three are *observed*: written by the executor while it ran. ``sameContentAs`` is
*inferred* from equal content hashes; it does not mean one was derived from the other.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Literal

from pydantic import BaseModel, Field

from neuroweave.store.db import ArtifactRecord, NodeExecutionRecord
from neuroweave.store.workspace import Workspace


class LineageNode(BaseModel):
    id: str
    type: Literal["artifact", "execution"]
    label: str
    data: dict[str, Any]


class LineageEdge(BaseModel):
    source: str
    target: str
    relation: Literal["used", "wasGeneratedBy", "reusedResultOf", "sameContentAs"]
    basis: Literal["observed", "inferred"]


class Lineage(BaseModel):
    root: str
    direction: Literal["upstream", "downstream"]
    nodes: list[LineageNode] = Field(default_factory=list)
    edges: list[LineageEdge] = Field(default_factory=list)
    truncated: bool = False


def _artifact_label(artifact: ArtifactRecord) -> str:
    if artifact.role == "input":
        return artifact.source_uri or artifact.id
    return f"{artifact.node_id}.{artifact.port}"


def _artifact_node(artifact: ArtifactRecord) -> LineageNode:
    return LineageNode(id=artifact.id, type="artifact", label=_artifact_label(artifact),
                       data=artifact.model_dump(mode="json"))


def _execution_node(execution: NodeExecutionRecord) -> LineageNode:
    data = execution.model_dump(mode="json", exclude={"traceback"})
    return LineageNode(id=execution.id, type="execution", label=execution.node_id, data=data)


class _Builder:
    def __init__(self, workspace: Workspace, root: str, direction: str, limit: int):
        self.db = workspace.db
        self.lineage = Lineage(root=root, direction=direction)  # type: ignore[arg-type]
        self.seen: set[str] = set()
        self.edge_keys: set[tuple[str, str, str]] = set()
        self.limit = limit

    def add_node(self, node: LineageNode) -> bool:
        if node.id in self.seen:
            return False
        if len(self.seen) >= self.limit:
            self.lineage.truncated = True
            return False
        self.seen.add(node.id)
        self.lineage.nodes.append(node)
        return True

    def add_edge(self, source: str, target: str, relation: str, basis: str = "observed") -> None:
        key = (source, target, relation)
        if key not in self.edge_keys:
            self.edge_keys.add(key)
            self.lineage.edges.append(LineageEdge(source=source, target=target,
                                                  relation=relation, basis=basis))  # type: ignore[arg-type]


def upstream_lineage(workspace: Workspace, artifact_id: str, *, limit: int = 500) -> Lineage:
    """Everything that contributed to ``artifact_id``: producing executions and their inputs."""
    db = workspace.db
    root = db.get_artifact(artifact_id)
    if root is None:
        raise KeyError(f"Artifact '{artifact_id}' does not exist.")
    builder = _Builder(workspace, artifact_id, "upstream", limit)
    queue: deque[ArtifactRecord] = deque([root])
    builder.add_node(_artifact_node(root))
    while queue:
        artifact = queue.popleft()
        if artifact.node_execution_id is None:
            continue
        execution = db.get_node_execution(artifact.node_execution_id)
        if execution is None:
            continue
        builder.add_node(_execution_node(execution))
        builder.add_edge(execution.id, artifact.id, "wasGeneratedBy")
        if execution.cache_hit and execution.cache_source_id:
            origin = db.get_node_execution(execution.cache_source_id)
            if origin is not None:
                builder.add_node(_execution_node(origin))
                builder.add_edge(origin.id, execution.id, "reusedResultOf")
        for record in db.inputs_of(execution.id):
            source = db.get_artifact(record.artifact_id)
            if source is None:
                continue
            builder.add_edge(source.id, execution.id, "used")
            if builder.add_node(_artifact_node(source)):
                queue.append(source)
    return builder.lineage


def downstream_lineage(workspace: Workspace, artifact_id: str, *, limit: int = 500) -> Lineage:
    """Everything derived from ``artifact_id`` across all recorded runs."""
    db = workspace.db
    root = db.get_artifact(artifact_id)
    if root is None:
        raise KeyError(f"Artifact '{artifact_id}' does not exist.")
    builder = _Builder(workspace, artifact_id, "downstream", limit)
    builder.add_node(_artifact_node(root))
    queue: deque[ArtifactRecord] = deque([root])
    while queue:
        artifact = queue.popleft()
        for record in db.consumers_of(artifact.id):
            execution = db.get_node_execution(record.node_execution_id)
            if execution is None:
                continue
            builder.add_node(_execution_node(execution))
            builder.add_edge(artifact.id, execution.id, "used")
            for output in db.outputs_of(execution.id):
                builder.add_edge(execution.id, output.id, "wasGeneratedBy")
                if builder.add_node(_artifact_node(output)):
                    queue.append(output)
    for twin in db.artifacts_with_hash(root.content_hash):
        if twin.id != root.id and twin.reused_from != root.id and root.reused_from != twin.id:
            if builder.add_node(_artifact_node(twin)):
                builder.add_edge(root.id, twin.id, "sameContentAs", "inferred")
    return builder.lineage
