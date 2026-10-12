"""Content-addressed artifact bytes and value serialisers.

Bytes live at ``artifacts/objects/<hash[:2]>/<hash>``; metadata lives in SQLite. The same
content produced twice is stored once, while each production keeps its own artifact record.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from neuroweave.datatypes import Figure, Markdown, Table
from neuroweave.kernel.types import is_json_value
from neuroweave.store.files import SHA256_PATTERN, atomic_write_bytes

_CHUNK = 1024 * 1024


class ArtifactIntegrityError(RuntimeError):
    pass


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = root
        self.objects = root / "objects"
        self.objects.mkdir(parents=True, exist_ok=True)

    def path_for(self, content_hash: str) -> Path:
        if not SHA256_PATTERN.match(content_hash):
            raise ValueError(f"Invalid content hash {content_hash!r}.")
        return self.objects / content_hash[:2] / content_hash

    def put_bytes(self, data: bytes) -> tuple[str, int]:
        digest = hashlib.sha256(data).hexdigest()
        path = self.path_for(digest)
        if not (path.is_file() and hash_file(path) == digest):
            atomic_write_bytes(path, data)
        return digest, len(data)

    def exists(self, content_hash: str) -> bool:
        return self.path_for(content_hash).is_file()

    def get_bytes(self, content_hash: str, *, verify: bool = True) -> bytes:
        path = self.path_for(content_hash)
        if not path.is_file():
            raise ArtifactIntegrityError(f"Artifact content {content_hash} is missing.")
        data = path.read_bytes()
        if verify and hashlib.sha256(data).hexdigest() != content_hash:
            raise ArtifactIntegrityError(
                f"Artifact content {content_hash} is corrupted: stored bytes no longer match "
                "their hash."
            )
        return data

    def verify(self, content_hash: str) -> bool:
        path = self.path_for(content_hash)
        return path.is_file() and hash_file(path) == content_hash


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------- serialisation


@dataclass(frozen=True)
class Serialized:
    data: bytes
    serializer: str
    media_type: str
    kind: str
    python_type: str


def _type_name(value: Any) -> str:
    cls = type(value)
    return cls.__name__ if cls.__module__ == "builtins" else f"{cls.__module__}.{cls.__qualname__}"


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def serialize(value: Any) -> Serialized:
    """Choose a deterministic format for ``value``; unknown objects fall back to pickle."""
    name = _type_name(value)
    if isinstance(value, Table):
        return Serialized(_json_bytes(value.to_json()), "table/v1",
                          "application/vnd.neuroweave.table+json", "table", name)
    if isinstance(value, Figure):
        return Serialized(value.svg.encode("utf-8"), "figure/v1", "image/svg+xml", "figure", name)
    if isinstance(value, Markdown):
        return Serialized(value.text.encode("utf-8"), "markdown/v1", "text/markdown", "report",
                          name)
    if isinstance(value, bytes):
        return Serialized(value, "bytes/v1", "application/octet-stream", "binary", name)
    if isinstance(value, str):
        return Serialized(value.encode("utf-8"), "text/v1", "text/plain", "text", name)
    if is_json_value(value):
        return Serialized(_json_bytes(value), "json/v1", "application/json", "value", name)
    return Serialized(pickle.dumps(value, protocol=5), "pickle/v1",
                      "application/vnd.python.pickle", "object", name)


def deserialize(data: bytes, serializer: str) -> Any:
    """Decode bytes produced by ``serialize``. Callers must verify the hash first: pickle
    content is only loaded because it was written by this workspace's own runs."""
    if serializer == "table/v1":
        return Table.from_json(json.loads(data))
    if serializer == "figure/v1":
        return Figure(data.decode("utf-8"))
    if serializer == "markdown/v1":
        return Markdown(data.decode("utf-8"))
    if serializer == "bytes/v1":
        return data
    if serializer == "text/v1":
        return data.decode("utf-8")
    if serializer == "json/v1":
        return json.loads(data)
    if serializer == "pickle/v1":
        return pickle.loads(data)  # noqa: S301 - hash-verified, self-produced content
    raise ValueError(f"Unknown serializer {serializer!r}.")


def guess_media_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


TEXT_MEDIA_TYPES = {
    "application/json",
    "application/vnd.neuroweave.table+json",
    "image/svg+xml",
    "text/markdown",
    "text/plain",
    "text/csv",
}
