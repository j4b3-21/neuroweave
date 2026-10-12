"""Deterministic serialisation of workflows and other JSON documents."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from neuroweave.kernel.model import WORKFLOW_SCHEMA_VERSION, Workflow


def canonical_json(value: Any) -> str:
    """Compact, key-sorted JSON used for hashing. Rejects NaN/Infinity."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pretty_json(value: Any) -> str:
    """Human-readable, key-sorted JSON with a trailing newline (stable diffs)."""
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def dump_workflow(workflow: Workflow) -> str:
    return pretty_json(workflow.model_dump(mode="json"))


def load_workflow(text: str) -> Workflow:
    data = json.loads(text)
    version = data.get("schema_version", WORKFLOW_SCHEMA_VERSION)
    if version != WORKFLOW_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported workflow schema_version {version}; "
            f"this NeuroWeave reads version {WORKFLOW_SCHEMA_VERSION}."
        )
    return Workflow.model_validate(data)


def snapshot_hash(workflow: Workflow) -> str:
    """Content identity of a workflow definition (distinct from the workflow id)."""
    return sha256_text(canonical_json(workflow.model_dump(mode="json")))
