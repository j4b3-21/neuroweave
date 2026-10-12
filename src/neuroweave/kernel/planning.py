"""Dependency analysis and deterministic execution planning."""

from __future__ import annotations

import heapq
from collections import defaultdict

from neuroweave.kernel.model import Workflow


class CycleError(ValueError):
    def __init__(self, nodes: list[str]):
        self.nodes = nodes
        super().__init__("Workflow contains a cycle through: " + ", ".join(nodes))


def _adjacency(workflow: Workflow) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    children: dict[str, set[str]] = defaultdict(set)
    parents: dict[str, set[str]] = defaultdict(set)
    known = {n.id for n in workflow.nodes}
    for edge in workflow.edges:
        if edge.source in known and edge.target in known:
            children[edge.source].add(edge.target)
            parents[edge.target].add(edge.source)
    return children, parents


def topological_order(workflow: Workflow) -> list[str]:
    """Kahn's algorithm; ties broken by declaration order so plans are stable across runs."""
    index = {n.id: i for i, n in enumerate(workflow.nodes)}
    children, parents = _adjacency(workflow)
    remaining = {node_id: len(parents[node_id]) for node_id in index}
    ready = [(index[n], n) for n, count in remaining.items() if count == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        _, node_id = heapq.heappop(ready)
        order.append(node_id)
        for child in children[node_id]:
            remaining[child] -= 1
            if remaining[child] == 0:
                heapq.heappush(ready, (index[child], child))
    if len(order) != len(index):
        stuck = sorted((n for n in index if n not in order), key=index.__getitem__)
        raise CycleError(stuck)
    return order


def downstream(workflow: Workflow, node_ids: set[str] | list[str]) -> set[str]:
    """All nodes that (transitively) depend on any of ``node_ids``, excluding the seeds."""
    children, _ = _adjacency(workflow)
    return _reach(children, set(node_ids))


def upstream(workflow: Workflow, node_ids: set[str] | list[str]) -> set[str]:
    """All nodes that ``node_ids`` (transitively) depend on, excluding the seeds."""
    _, parents = _adjacency(workflow)
    return _reach(parents, set(node_ids))


def _reach(graph: dict[str, set[str]], seeds: set[str]) -> set[str]:
    seen: set[str] = set()
    stack = list(seeds)
    while stack:
        for nxt in graph[stack.pop()]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen - seeds


def depths(workflow: Workflow) -> dict[str, int]:
    """Longest-path depth of each node (used for automatic layout)."""
    _, parents = _adjacency(workflow)
    result: dict[str, int] = {}
    for node_id in topological_order(workflow):
        result[node_id] = max((result[p] + 1 for p in parents[node_id]), default=0)
    return result
