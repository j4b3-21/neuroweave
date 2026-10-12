"""Small, dependency-free research data types with deterministic serialisation.

These give the type system and the Studio something concrete to understand (tables are
previewable, figures renderable, reports readable) without requiring pandas or matplotlib.
Nodes can still use any Python object; unknown objects are stored with the pickle fallback.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

Cell = str | int | float | bool | None


def _cell(value: Any) -> Cell:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    raise TypeError(f"Table cells must be str, int, float, bool or None; got {type(value)}.")


@dataclass(frozen=True)
class Table:
    """An immutable column-oriented table of JSON scalar cells."""

    columns: tuple[str, ...]
    rows: tuple[tuple[Cell, ...], ...]

    def __post_init__(self) -> None:
        columns = tuple(str(c) for c in self.columns)
        if len(set(columns)) != len(columns):
            raise ValueError(f"Duplicate column names in {columns}.")
        rows = tuple(tuple(_cell(v) for v in row) for row in self.rows)
        for index, row in enumerate(rows):
            if len(row) != len(columns):
                raise ValueError(
                    f"Row {index} has {len(row)} cells but the table has {len(columns)} columns."
                )
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "rows", rows)

    @classmethod
    def from_records(
        cls, records: Iterable[Mapping[str, Any]], columns: Sequence[str] | None = None
    ) -> Table:
        records = list(records)
        if columns is None:
            seen: dict[str, None] = {}
            for record in records:
                for key in record:
                    seen.setdefault(key, None)
            columns = list(seen)
        return cls(tuple(columns), tuple(tuple(r.get(c) for c in columns) for r in records))

    @classmethod
    def from_csv(cls, path: str | Path, *, infer_types: bool = True) -> Table:
        with open(path, newline="", encoding="utf-8") as handle:
            return cls.from_csv_text(handle.read(), infer_types=infer_types)

    @classmethod
    def from_csv_text(cls, text: str, *, infer_types: bool = True) -> Table:
        reader = csv.reader(io.StringIO(text))
        try:
            header = next(reader)
        except StopIteration:
            return cls((), ())
        rows = [tuple(_parse(v) if infer_types else v for v in row) for row in reader if row]
        return cls(tuple(header), tuple(rows))

    @property
    def num_rows(self) -> int:
        return len(self.rows)

    def column(self, name: str) -> list[Cell]:
        try:
            index = self.columns.index(name)
        except ValueError:
            raise KeyError(f"No column {name!r}; columns are {list(self.columns)}.") from None
        return [row[index] for row in self.rows]

    def records(self) -> list[dict[str, Cell]]:
        return [dict(zip(self.columns, row, strict=True)) for row in self.rows]

    def to_csv_text(self) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(self.columns)
        writer.writerows(self.rows)
        return buffer.getvalue()

    def to_json(self) -> dict[str, Any]:
        return {"columns": list(self.columns), "rows": [list(r) for r in self.rows]}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Table:
        return cls(tuple(data["columns"]), tuple(tuple(r) for r in data["rows"]))


def _parse(value: str) -> Cell:
    stripped = value.strip()
    if stripped == "":
        return None
    for convert in (int, float):
        try:
            result = convert(stripped)
        except ValueError:
            continue
        if isinstance(result, float) and not math.isfinite(result):
            return None
        return result
    lowered = stripped.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    return value


@dataclass(frozen=True)
class Figure:
    """A vector figure stored as SVG markup."""

    svg: str

    def __post_init__(self) -> None:
        if "<svg" not in self.svg:
            raise ValueError("Figure.svg must contain an <svg> element.")


@dataclass(frozen=True)
class Markdown:
    """A Markdown document, e.g. a generated research report."""

    text: str
