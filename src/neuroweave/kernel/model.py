"""The workflow graph: node instances connected by data-flow edges."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

WORKFLOW_SCHEMA_VERSION = 1
IDENTIFIER_PATTERN = r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$"
WORKFLOW_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = 0.0
    y: float = 0.0


class NodeInstance(BaseModel):
    """One use of a node definition inside a workflow."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=IDENTIFIER_PATTERN)
    type: str = Field(min_length=1, description="NodeDefinition.id")
    label: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    position: Position = Field(default_factory=Position)


class Edge(BaseModel):
    """Data flows from ``source.source_port`` (an output) to ``target.target_port`` (an input)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    source_port: str
    target: str
    target_port: str

    @property
    def key(self) -> str:
        return f"{self.source}.{self.source_port}->{self.target}.{self.target_port}"


class Workflow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = WORKFLOW_SCHEMA_VERSION
    id: str = Field(pattern=WORKFLOW_ID_PATTERN)
    name: str = Field(min_length=1)
    description: str = ""
    nodes: list[NodeInstance] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)

    def node(self, node_id: str) -> NodeInstance | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def incoming(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.target == node_id]

    def outgoing(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.source == node_id]
