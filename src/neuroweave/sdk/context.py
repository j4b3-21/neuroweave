"""Information available to a node function while it executes inside a run."""

from __future__ import annotations

import math
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Direction = Literal["maximize", "minimize"]


@dataclass
class MetricEntry:
    name: str
    value: float
    step: int | None
    direction: Direction | None


@dataclass
class NodeContext:
    run_id: str
    node_id: str
    node_execution_id: str
    seed: int
    project_root: Path
    metrics: list[MetricEntry] = field(default_factory=list)


_current: ContextVar[NodeContext | None] = ContextVar("neuroweave_node_context", default=None)


def current_context() -> NodeContext | None:
    """The executing node's context, or None when called outside a NeuroWeave run."""
    return _current.get()


def log_metric(
    name: str, value: float, *, step: int | None = None, direction: Direction | None = None
) -> None:
    """Record a metric for the current node execution.

    Outside a run (e.g. calling the function directly in a notebook) this is a no-op, so
    node functions remain usable as plain Python.
    ``direction`` documents whether larger or smaller is preferable; NeuroWeave displays it
    but never declares a run "better" on that basis alone.
    """
    if not isinstance(name, str) or not name:
        raise ValueError("Metric name must be a non-empty string.")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Metric {name!r} must be a number, got {type(value).__name__}.")
    if not math.isfinite(value):
        raise ValueError(f"Metric {name!r} must be finite, got {value}.")
    if direction not in (None, "maximize", "minimize"):
        raise ValueError("direction must be 'maximize', 'minimize' or None.")
    context = _current.get()
    if context is None:
        return
    context.metrics.append(MetricEntry(name, float(value), step, direction))
