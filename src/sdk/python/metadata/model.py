from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParameterMetadata:
    name: str
    type: str
    default: Any
    required: bool


@dataclass
class NodeMetadata:
    name: str
    qualified_name: str

    category: str | None = None
    description: str | None = None

    parameters: list[ParameterMetadata] = field(default_factory=list)

    input_types: dict[str, str] = field(default_factory=dict)

    output_type: str | None = None

    cache_enabled: bool = True
    version_enabled: bool = True

    tags: list[str] = field(default_factory=list)