"""Best-effort runtime checks of values against real Python annotations.

Checks are shallow (``list[int]`` checks that the value is a list, not every element) and
unknown typing constructs are accepted. This catches wiring mistakes early; it is not a
proof of type safety.
"""

from __future__ import annotations

import inspect
import pathlib
import types
import typing
from typing import Any, Literal


def matches(value: Any, annotation: Any) -> bool:
    if annotation is inspect.Parameter.empty or annotation is Any or annotation is object:
        return True
    if annotation is None or annotation is type(None):
        return value is None
    if isinstance(annotation, (str, typing.TypeVar)):
        return True
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is typing.Annotated:
        return matches(value, args[0])
    if origin in (typing.Union, types.UnionType):
        return any(matches(value, member) for member in args)
    if origin is Literal:
        return value in args
    if origin is not None:
        if isinstance(origin, type):
            return isinstance(value, origin)
        return True
    if isinstance(annotation, type):
        if annotation is float:
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if annotation is int:
            return isinstance(value, int) and not isinstance(value, bool)
        if issubclass(annotation, pathlib.PurePath):
            return isinstance(value, (pathlib.PurePath, str))
        return isinstance(value, annotation)
    return True


def describe(annotation: Any) -> str:
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation).replace("typing.", "")
