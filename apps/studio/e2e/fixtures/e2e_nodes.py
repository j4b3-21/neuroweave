"""Nodes used only by the Studio browser tests in apps/studio/e2e.

They are copied into a temporary project next to the research demo. ``explode`` fails on
purpose and ``random_token`` ignores the run seed on purpose, so the tests can exercise
failure handling and a reproduction that does not match.
"""

from __future__ import annotations

import os

from neuroweave import node


@node(category="E2E")
def make_numbers(count: int = 5) -> list[int]:
    """The integers 1..count."""
    return list(range(1, count + 1))


@node(category="E2E")
def explode(
    values: list[int], message: str = "Deliberate failure for the browser test"
) -> list[int]:
    """Always raises."""
    print(f"explode received {len(values)} values")
    raise RuntimeError(message)


@node(category="E2E")
def total(values: list[int]) -> int:
    """Sum of the values."""
    return sum(values)


@node(category="E2E", cache=False)
def random_token(nbytes: int = 8) -> str:
    """Nondeterministic: reads the OS random source instead of the seeded generator."""
    return os.urandom(nbytes).hex()
