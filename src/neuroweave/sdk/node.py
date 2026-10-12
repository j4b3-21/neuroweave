"""The ``@node`` decorator."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, TypeVar, overload

from neuroweave.sdk.introspection import build_node
from neuroweave.sdk.registry import NodeRegistry, default_registry

F = TypeVar("F", bound=Callable[..., Any])


@overload
def node(func: F, /) -> F: ...


@overload
def node(
    *,
    name: str | None = ...,
    label: str | None = ...,
    version: str | int = ...,
    category: str | None = ...,
    description: str | None = ...,
    tags: Sequence[str] = ...,
    outputs: Sequence[str] | Mapping[str, Any] | None = ...,
    cache: bool = ...,
    registry: NodeRegistry | None = ...,
) -> Callable[[F], F]: ...


def node(
    func: Callable[..., Any] | None = None,
    /,
    *,
    name: str | None = None,
    label: str | None = None,
    version: str | int = "1",
    category: str | None = None,
    description: str | None = None,
    tags: Sequence[str] = (),
    outputs: Sequence[str] | Mapping[str, Any] | None = None,
    cache: bool = True,
    registry: NodeRegistry | None = None,
):
    """Register a Python function as a NeuroWeave node.

    Usable bare (``@node``) or with options (``@node(version="2", outputs=["train", "test"])``).
    The function is returned unchanged, so it stays callable from ordinary Python.

    * Every parameter becomes an input port. Parameters whose annotation is a JSON-editable
      type (``int``, ``float``, ``str``, ``bool``, ``Literal``, ``Path``, lists/dicts of
      those) can also be set as literal parameters in a workflow.
    * The return value becomes the ``output`` port. With ``outputs=[...]`` the function must
      return a dict with exactly those keys, or a tuple in the same order.
    * ``version`` is the researcher's declared version; bump it when behaviour changes in a
      way the source hash cannot see (e.g. a helper function changed).
    * ``cache=False`` disables result reuse (use it for nodes with side effects or
      non-reproducible randomness).
    """

    def decorate(target: F) -> F:
        registered = build_node(
            target,
            name=name,
            label=label,
            version=version,
            category=category,
            description=description,
            tags=tags,
            outputs=outputs,
            cache=cache,
        )
        (default_registry if registry is None else registry).register(registered)
        target.__neuroweave_node__ = registered.definition  # type: ignore[attr-defined]
        return target

    if func is not None:
        return decorate(func)
    return decorate


Node = node
