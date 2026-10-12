"""Serialisable descriptions of reusable computational operations (node definitions).

A ``NodeDefinition`` is what the graph kernel, the API and the Studio know about a node.
It never contains the callable itself; that lives in ``neuroweave.sdk.registry``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from neuroweave.kernel.types import TypeSpec, Widget


class PortSpec(BaseModel):
    name: str
    type: TypeSpec
    description: str | None = None
    required: bool = True
    has_default: bool = False
    default: Any = None
    default_repr: str | None = None
    editable: bool = False
    widget: Widget | None = None
    choices: list[Any] | None = None


class NodeDefinition(BaseModel):
    id: str = Field(description="Stable identifier: '<module>:<qualname>'.")
    name: str
    label: str
    module: str
    qualname: str
    version: str = "1"
    code_hash: str | None = Field(
        default=None, description="SHA-256 of the function source, or None when unavailable."
    )
    description: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    inputs: list[PortSpec] = Field(default_factory=list)
    outputs: list[PortSpec] = Field(default_factory=list)
    cache: bool = True

    def input(self, name: str) -> PortSpec | None:
        return next((p for p in self.inputs if p.name == name), None)

    def output(self, name: str) -> PortSpec | None:
        return next((p for p in self.outputs if p.name == name), None)
