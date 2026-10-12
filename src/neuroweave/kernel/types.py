"""Static type descriptions for node ports.

A ``TypeSpec`` is a serialisable description of a Python annotation. It drives three
separate concerns that must not be confused:

* static connection checks between ports (``compatibility``),
* validation of JSON parameter values entered by a user (``validate_value``),
* which UI control the Studio may generate (``widget_for``).

None of these imply runtime safety; the runtime performs its own checks against the
real annotation objects (see ``neuroweave.runtime.typecheck``).
"""

from __future__ import annotations

import collections.abc
import inspect
import math
import pathlib
import types
import typing
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

Kind = Literal[
    "any", "none", "primitive", "list", "dict", "optional", "union", "literal", "file", "domain"
]
Level = Literal["ok", "warning", "error"]

_PRIMITIVES: dict[type, str] = {
    int: "int", float: "float", str: "str", bool: "bool", bytes: "bytes",
}
_SEQUENCES: dict[Any, str] = {
    list: "list",
    tuple: "tuple",
    set: "set",
    frozenset: "set",
    collections.abc.Sequence: "list",
    collections.abc.MutableSequence: "list",
    collections.abc.Iterable: "list",
    collections.abc.Set: "set",
}
_MAPPINGS = (dict, collections.abc.Mapping, collections.abc.MutableMapping)


class TypeSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Kind
    name: str
    args: tuple[TypeSpec, ...] = ()
    values: tuple[Any, ...] = ()
    bases: tuple[str, ...] = ()

    def __str__(self) -> str:
        if self.kind == "optional":
            return f"{self.args[0]} | None"
        if self.kind == "union":
            return " | ".join(str(a) for a in self.args)
        if self.kind == "literal":
            return "Literal[" + ", ".join(repr(v) for v in self.values) + "]"
        if self.kind in ("list", "dict") and self.args:
            return f"{self.name}[" + ", ".join(str(a) for a in self.args) + "]"
        return self.name

    @property
    def display(self) -> str:
        return str(self)


ANY = TypeSpec(kind="any", name="Any")
NONE = TypeSpec(kind="none", name="None")
FILE = TypeSpec(kind="file", name="File")


def optional(inner: TypeSpec) -> TypeSpec:
    if inner.kind in ("optional", "any", "none"):
        return inner
    return TypeSpec(kind="optional", name="Optional", args=(inner,))


def _qualified(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def from_annotation(tp: Any) -> TypeSpec:
    """Translate a Python annotation into a TypeSpec. Unknown constructs become ``Any``."""
    if tp is inspect.Parameter.empty or tp is Any or tp is object:
        return ANY
    if tp is None or tp is type(None):
        return NONE
    if isinstance(tp, str):
        return TypeSpec(kind="domain", name=tp)
    if isinstance(tp, type) and tp in _PRIMITIVES:
        return TypeSpec(kind="primitive", name=_PRIMITIVES[tp])
    if isinstance(tp, type) and issubclass(tp, pathlib.PurePath):
        return FILE

    origin = typing.get_origin(tp)
    args = typing.get_args(tp)

    if origin is typing.Annotated:
        return from_annotation(args[0])
    if origin in (typing.Union, types.UnionType):
        members = [a for a in args if a is not type(None)]
        if len(members) == 1:
            inner = from_annotation(members[0])
        else:
            inner = TypeSpec(
                kind="union", name="Union", args=tuple(from_annotation(m) for m in members)
            )
        return optional(inner) if len(members) < len(args) else inner
    if origin is Literal:
        return TypeSpec(kind="literal", name="Literal", values=tuple(args))
    if origin in _SEQUENCES or tp in _SEQUENCES:
        container = origin if origin is not None else tp
        element: Any = Any
        if args:
            if container is tuple:
                element = args[0] if len(args) == 2 and args[1] is Ellipsis else Any
            else:
                element = args[0]
        return TypeSpec(kind="list", name=_SEQUENCES[container], args=(from_annotation(element),))
    if origin in _MAPPINGS or tp in _MAPPINGS:
        key, value = (args[0], args[1]) if len(args) == 2 else (Any, Any)
        return TypeSpec(kind="dict", name="dict",
                        args=(from_annotation(key), from_annotation(value)))
    if isinstance(tp, typing.TypeVar):
        return ANY
    if isinstance(tp, type):
        bases = tuple(_qualified(c) for c in tp.__mro__ if c is not object)
        return TypeSpec(kind="domain", name=tp.__name__, bases=bases)
    return ANY


def from_value(value: Any) -> TypeSpec:
    """Infer a TypeSpec from a default value (used for unannotated parameters)."""
    if value is None:
        return ANY
    if type(value) in _PRIMITIVES:
        return TypeSpec(kind="primitive", name=_PRIMITIVES[type(value)])
    if isinstance(value, pathlib.PurePath):
        return FILE
    if isinstance(value, list):
        return TypeSpec(kind="list", name="list", args=(ANY,))
    if isinstance(value, dict):
        return TypeSpec(kind="dict", name="dict", args=(ANY, ANY))
    return ANY


# --------------------------------------------------------------------------- compatibility

_ORDER = {"ok": 0, "warning": 1, "error": 2}


def _worst(results: list[tuple[Level, str | None]]) -> tuple[Level, str | None]:
    return max(results, key=lambda r: _ORDER[r[0]])


def _best(results: list[tuple[Level, str | None]]) -> tuple[Level, str | None]:
    return min(results, key=lambda r: _ORDER[r[0]])


def _literal_value_type(value: Any) -> TypeSpec:
    return from_value(value) if value is not None else NONE


def compatibility(source: TypeSpec, target: TypeSpec) -> tuple[Level, str | None]:
    """Can a value described by ``source`` flow into a port described by ``target``?

    Returns ``("ok", None)``, ``("warning", reason)`` when the connection may fail at runtime,
    or ``("error", reason)`` when it can never be valid.
    """
    ok: tuple[Level, str | None] = ("ok", None)
    if target.kind == "any" or source.kind == "any":
        return ok

    if target.kind == "optional":
        if source.kind == "none":
            return ok
        inner = source.args[0] if source.kind == "optional" else source
        return compatibility(inner, target.args[0])
    if source.kind == "optional":
        level, message = compatibility(source.args[0], target)
        if level == "error":
            return level, message
        return "warning", f"{source} may be None but {target} does not accept None"

    if source.kind == "union":
        results = [compatibility(member, target) for member in source.args]
        if all(r[0] == "ok" for r in results):
            return ok
        if all(r[0] == "error" for r in results):
            return "error", f"no member of {source} is compatible with {target}"
        return "warning", f"only some members of {source} are accepted by {target}"
    if target.kind == "union":
        level, _ = _best([compatibility(source, member) for member in target.args])
        return (level, None) if level != "error" else ("error", f"{source} is not one of {target}")

    if source.kind == "literal":
        if target.kind == "literal":
            accepted = [v for v in source.values if v in target.values]
            if len(accepted) == len(source.values):
                return ok
            if not accepted:
                return "error", f"{source} shares no values with {target}"
            return "warning", f"some values of {source} are not allowed by {target}"
        return _worst([compatibility(_literal_value_type(v), target) for v in source.values])
    if target.kind == "literal":
        value_types = {_literal_value_type(v).name for v in target.values}
        if source.kind == "primitive" and source.name in value_types:
            return "warning", f"{source} is only accepted when its value is one of {target}"
        return "error", f"{source} is not compatible with {target}"

    if source.kind == "none":
        return "error", f"None is not accepted by {target}"

    if source.kind == "primitive" and target.kind == "primitive":
        if source.name == target.name or (source.name == "int" and target.name == "float"):
            return ok
        return "error", f"{source} is not compatible with {target}"

    if target.kind == "file":
        if source.kind == "file" or (source.kind == "primitive" and source.name == "str"):
            return ok
        return "error", f"{source} is not a file path"

    if source.kind == "list" and target.kind == "list":
        return compatibility(source.args[0], target.args[0])
    if source.kind == "dict" and target.kind == "dict":
        return _worst(
            [
                compatibility(source.args[0], target.args[0]),
                compatibility(source.args[1], target.args[1]),
            ]
        )

    if source.kind == "domain" and target.kind == "domain":
        if target.bases and source.bases:
            if target.bases[0] in source.bases:
                return ok
        elif source.name == target.name:
            return ok
        return "error", f"{source} is not compatible with {target}"

    return "error", f"{source} is not compatible with {target}"


# --------------------------------------------------------------------------- parameters

Widget = Literal["integer", "number", "text", "checkbox", "select", "file", "json"]


def _json_editable(spec: TypeSpec) -> bool:
    """Whether a value of this type can be written as JSON (``Any`` only inside containers)."""
    if spec.kind == "primitive":
        return spec.name != "bytes"
    if spec.kind in ("literal", "file", "none", "any"):
        return True
    if spec.kind in ("optional", "list"):
        return _json_editable(spec.args[0])
    if spec.kind == "dict":
        key = spec.args[0]
        return (key.kind == "any" or key.name == "str") and _json_editable(spec.args[1])
    if spec.kind == "union":
        return all(_json_editable(a) for a in spec.args)
    return False


def widget_for(spec: TypeSpec) -> Widget | None:
    """The UI control appropriate for a literal value of this type, or None if not editable."""
    if spec.kind == "optional":
        return widget_for(spec.args[0])
    if spec.kind == "primitive":
        return {"int": "integer", "float": "number", "str": "text", "bool": "checkbox"}.get(
            spec.name
        )  # type: ignore[return-value]
    if spec.kind == "literal":
        return "select"
    if spec.kind == "file":
        return "file"
    if spec.kind in ("list", "dict", "union") and _json_editable(spec):
        return "json"
    return None


def validate_value(spec: TypeSpec, value: Any) -> str | None:
    """Validate a JSON parameter value against a TypeSpec. Returns an error message or None."""
    if spec.kind == "any":
        return None if _is_json(value) else "value is not JSON-serialisable"
    if spec.kind == "none":
        return None if value is None else "expected null"
    if spec.kind == "optional":
        return None if value is None else validate_value(spec.args[0], value)
    if spec.kind == "union":
        errors = [validate_value(member, value) for member in spec.args]
        return None if any(e is None for e in errors) else f"expected {spec}"
    if spec.kind == "literal":
        return None if value in spec.values else f"expected one of {list(spec.values)}"
    if spec.kind == "file":
        return None if isinstance(value, str) and value.strip() else "expected a file path"
    if spec.kind == "primitive":
        if spec.name == "bool":
            return None if isinstance(value, bool) else "expected a boolean"
        if spec.name == "int":
            ok = isinstance(value, int) and not isinstance(value, bool)
            return None if ok else "expected an integer"
        if spec.name == "float":
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
            if ok and not math.isfinite(float(value)):
                return "expected a finite number"
            return None if ok else "expected a number"
        if spec.name == "str":
            return None if isinstance(value, str) else "expected a string"
        return f"{spec} values cannot be entered as parameters"
    if spec.kind == "list":
        if not isinstance(value, list):
            return "expected a list"
        for index, item in enumerate(value):
            error = validate_value(spec.args[0], item)
            if error:
                return f"item {index}: {error}"
        return None
    if spec.kind == "dict":
        if not isinstance(value, dict):
            return "expected an object"
        for key, item in value.items():
            if not isinstance(key, str):
                return "object keys must be strings"
            error = validate_value(spec.args[1], item)
            if error:
                return f"key {key!r}: {error}"
        return None
    return f"{spec} values cannot be entered as parameters"


def _is_json(value: Any) -> bool:
    if value is None or isinstance(value, (bool, str)):
        return True
    if isinstance(value, (int, float)):
        return not isinstance(value, float) or math.isfinite(value)
    if isinstance(value, list):
        return all(_is_json(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _is_json(v) for k, v in value.items())
    return False


def is_json_value(value: Any) -> bool:
    return _is_json(value)
