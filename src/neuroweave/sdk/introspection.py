"""Turn a Python function into a NodeDefinition by inspecting its signature."""

from __future__ import annotations

import hashlib
import inspect
import pathlib
import textwrap
import typing
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from neuroweave.kernel.definitions import NodeDefinition, PortSpec
from neuroweave.kernel.types import (
    ANY,
    from_annotation,
    from_value,
    is_json_value,
    optional,
    widget_for,
)

_EMPTY = inspect.Parameter.empty


class NodeDefinitionError(TypeError):
    """Raised when a function cannot be turned into a node."""


@dataclass(frozen=True)
class RegisteredNode:
    """A node definition together with the callable that implements it (in-process only)."""

    definition: NodeDefinition
    func: Callable[..., Any]
    input_annotations: Mapping[str, Any]
    output_annotations: Mapping[str, Any]


def _type_hints(func: Callable[..., Any]) -> dict[str, Any]:
    try:
        return typing.get_type_hints(func, include_extras=True)
    except Exception:
        # Unresolvable forward references: fall back to the raw annotations (strings are
        # treated as opaque domain type names by the type system).
        return dict(getattr(func, "__annotations__", {}))


def source_hash(func: Callable[..., Any]) -> str | None:
    try:
        source = textwrap.dedent(inspect.getsource(func))
    except (OSError, TypeError):
        return None
    normalised = source.replace("\r\n", "\n")
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def default_label(name: str) -> str:
    return " ".join(word.capitalize() for word in name.strip("_").split("_") if word) or name


def _input_port(parameter: inspect.Parameter, annotation: Any) -> PortSpec:
    has_default = parameter.default is not _EMPTY
    if annotation is not _EMPTY:
        spec = from_annotation(annotation)
    elif has_default:
        spec = from_value(parameter.default)
    else:
        spec = ANY
    if has_default and parameter.default is None:
        spec = optional(spec)

    default: Any = None
    default_repr: str | None = None
    if has_default:
        value = parameter.default
        if isinstance(value, pathlib.PurePath):
            value = str(value)
        if is_json_value(value):
            default = value
        else:
            default_repr = repr(parameter.default)

    widget = widget_for(spec)
    inner = spec.args[0] if spec.kind == "optional" else spec
    return PortSpec(
        name=parameter.name,
        type=spec,
        required=not has_default,
        has_default=has_default,
        default=default,
        default_repr=default_repr,
        editable=widget is not None,
        widget=widget,
        choices=list(inner.values) if inner.kind == "literal" else None,
    )


def _output_ports(
    hints: dict[str, Any], outputs: Sequence[str] | Mapping[str, Any] | None
) -> tuple[list[PortSpec], dict[str, Any]]:
    returned = hints.get("return", _EMPTY)
    if outputs is None:
        if returned is None or returned is type(None):
            return [], {}
        return [PortSpec(name="output", type=from_annotation(returned))], {"output": returned}

    if isinstance(outputs, Mapping):
        annotations = dict(outputs)
    else:
        names = list(outputs)
        element_types: tuple[Any, ...] = ()
        if typing.get_origin(returned) is tuple:
            element_types = typing.get_args(returned)
        if len(element_types) == len(names) and Ellipsis not in element_types:
            annotations = dict(zip(names, element_types, strict=True))
        else:
            annotations = {name: _EMPTY for name in names}
    if not annotations:
        raise NodeDefinitionError("outputs= must name at least one output.")
    for name in annotations:
        if not name.isidentifier():
            raise NodeDefinitionError(f"Output name {name!r} is not a valid identifier.")
    ports = [PortSpec(name=n, type=from_annotation(a)) for n, a in annotations.items()]
    return ports, annotations


def build_node(
    func: Callable[..., Any],
    *,
    name: str | None = None,
    label: str | None = None,
    version: str | int = "1",
    category: str | None = None,
    description: str | None = None,
    tags: Sequence[str] = (),
    outputs: Sequence[str] | Mapping[str, Any] | None = None,
    cache: bool = True,
) -> RegisteredNode:
    if not callable(func) or not hasattr(func, "__qualname__"):
        raise NodeDefinitionError(f"@node can only decorate functions, got {func!r}.")
    signature = inspect.signature(func)
    hints = _type_hints(func)

    inputs: list[PortSpec] = []
    input_annotations: dict[str, Any] = {}
    for parameter in signature.parameters.values():
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            raise NodeDefinitionError(
                f"{func.__qualname__}: *args/**kwargs are not supported; every node input "
                "needs a name."
            )
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
            raise NodeDefinitionError(
                f"{func.__qualname__}: positional-only parameter '{parameter.name}' is not "
                "supported; nodes are invoked with keyword arguments."
            )
        annotation = hints.get(parameter.name, _EMPTY)
        input_annotations[parameter.name] = annotation
        inputs.append(_input_port(parameter, annotation))

    output_ports, output_annotations = _output_ports(hints, outputs)
    function_name = name or func.__name__
    definition = NodeDefinition(
        id=f"{func.__module__}:{func.__qualname__}",
        name=function_name,
        label=label or default_label(function_name),
        module=func.__module__,
        qualname=func.__qualname__,
        version=str(version),
        code_hash=source_hash(func),
        description=description or inspect.getdoc(func),
        category=category,
        tags=list(tags),
        inputs=inputs,
        outputs=output_ports,
        cache=cache,
    )
    return RegisteredNode(definition, func, input_annotations, output_annotations)
