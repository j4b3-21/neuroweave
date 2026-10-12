from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional

import pytest

from neuroweave.datatypes import Table
from neuroweave.kernel.types import (
    ANY,
    compatibility,
    from_annotation,
    validate_value,
    widget_for,
)


class Base:
    pass


class Derived(Base):
    pass


def spec(tp):
    return from_annotation(tp)


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        (int, "int"),
        (list[int], "list[int]"),
        (dict[str, float], "dict[str, float]"),
        (Optional[int], "int | None"),  # noqa: UP045
        (int | None, "int | None"),
        (int | str, "int | str"),
        (Literal["a", "b"], "Literal['a', 'b']"),
        (Path, "File"),
        (Table, "Table"),
        (Any, "Any"),
        (tuple[int, ...], "tuple[int]"),
    ],
)
def test_annotations_keep_structure(annotation, expected) -> None:
    assert str(spec(annotation)) == expected


def test_compatibility_rules() -> None:
    def level(a, b):
        return compatibility(spec(a), spec(b))[0]

    assert level(int, float) == "ok"
    assert level(float, int) == "error"
    assert level(bool, int) == "error"
    assert level(str, Path) == "ok"
    assert level(int | None, int) == "warning"
    assert level(int, int | None) == "ok"
    assert level(list[int], list[float]) == "ok"
    assert level(list[str], list[int]) == "error"
    assert level(Derived, Base) == "ok"
    assert level(Base, Derived) == "error"
    assert level(Table, dict[str, float]) == "error"
    assert level(Literal["a"], str) == "ok"
    assert level(str, Literal["a"]) == "warning"
    assert compatibility(ANY, spec(Table))[0] == "ok"


def test_widgets_only_for_editable_types() -> None:
    assert widget_for(spec(int)) == "integer"
    assert widget_for(spec(float)) == "number"
    assert widget_for(spec(bool)) == "checkbox"
    assert widget_for(spec(Literal["x", "y"])) == "select"
    assert widget_for(spec(Path)) == "file"
    assert widget_for(spec(list[str])) == "json"
    assert widget_for(spec(Table)) is None
    assert widget_for(ANY) is None
    assert widget_for(spec(bytes)) is None


def test_validate_value() -> None:
    assert validate_value(spec(int), 3) is None
    assert validate_value(spec(int), True) == "expected an integer"
    assert validate_value(spec(float), 2) is None
    assert validate_value(spec(float), float("nan")) == "expected a finite number"
    assert validate_value(spec(Literal["a"]), "b") is not None
    assert validate_value(spec(list[int]), [1, "x"]).startswith("item 1")
    assert validate_value(spec(int | None), None) is None
    assert validate_value(spec(Path), "") == "expected a file path"
