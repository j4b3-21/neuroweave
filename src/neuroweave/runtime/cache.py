"""Cache keys: when may a previous node result be reused?

A result is reused only when all of these are identical: node id, declared version, source
hash of the node function, literal parameters, content hashes (and formats) of every input,
the node's derived random seed, and the Python implementation/minor version.

Known blind spots (documented in docs/reproducibility.md): helper functions called by the
node, third-party package versions, and files the node reads without declaring them as
``Path`` inputs. Bump the node ``version`` or run with ``--no-cache`` when these change.
"""

from __future__ import annotations

from typing import Any

from neuroweave.kernel.definitions import NodeDefinition
from neuroweave.kernel.serialization import canonical_json, sha256_text
from neuroweave.runtime.environment import python_identity

CACHE_FORMAT = 1


def cache_key(
    definition: NodeDefinition,
    params: dict[str, Any],
    inputs: dict[str, str],
    seed: int,
) -> tuple[str | None, str | None]:
    """Return ``(key, None)`` or ``(None, reason)`` when equivalence cannot be established."""
    if not definition.cache:
        return None, "caching disabled for this node (cache=False)"
    if definition.code_hash is None:
        return None, "node source code is unavailable, so a code change could go unnoticed"
    payload = {
        "format": CACHE_FORMAT,
        "node": definition.id,
        "version": definition.version,
        "code": definition.code_hash,
        "params": params,
        "inputs": inputs,
        "seed": seed,
        "python": python_identity(),
    }
    try:
        return sha256_text(canonical_json(payload)), None
    except (TypeError, ValueError):
        return None, "parameters are not canonically serialisable"
