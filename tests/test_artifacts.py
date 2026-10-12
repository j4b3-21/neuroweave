from __future__ import annotations

import hashlib

import pytest

from neuroweave.datatypes import Figure, Markdown, Table
from neuroweave.store.artifacts import (
    ArtifactIntegrityError,
    ArtifactStore,
    deserialize,
    serialize,
)


class Custom:
    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return isinstance(other, Custom) and other.value == self.value


@pytest.mark.parametrize(
    ("value", "serializer", "kind"),
    [
        ({"b": 1, "a": [1.5, None, True]}, "json/v1", "value"),
        ("hello", "text/v1", "text"),
        (b"\x00\x01", "bytes/v1", "binary"),
        (Table(("x", "y"), ((1, "a"), (2, None))), "table/v1", "table"),
        (Figure("<svg></svg>"), "figure/v1", "figure"),
        (Markdown("# Title"), "markdown/v1", "report"),
        (Custom(3), "pickle/v1", "object"),
        (float("nan"), "pickle/v1", "object"),
    ],
)
def test_serializer_round_trip(value, serializer, kind) -> None:
    result = serialize(value)
    assert (result.serializer, result.kind) == (serializer, kind)
    restored = deserialize(result.data, result.serializer)
    if isinstance(value, float):
        assert restored != restored
    else:
        assert restored == value


def test_json_serialisation_is_deterministic() -> None:
    assert serialize({"b": 1, "a": 2}).data == serialize({"a": 2, "b": 1}).data


def test_store_hashes_deduplicates_and_detects_tampering(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    digest, size = store.put_bytes(b"research")
    assert digest == hashlib.sha256(b"research").hexdigest() and size == 8
    assert store.put_bytes(b"research")[0] == digest
    assert len(list(store.objects.rglob("*"))) == 2  # one shard dir + one object
    assert store.verify(digest)

    store.path_for(digest).write_bytes(b"tampered")
    assert not store.verify(digest)
    with pytest.raises(ArtifactIntegrityError, match="corrupted"):
        store.get_bytes(digest)


def test_store_rejects_path_traversal(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    with pytest.raises(ValueError):
        store.path_for("../../etc/passwd")


def test_table_validation() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        Table(("a", "a"), ())
    with pytest.raises(ValueError, match="Row 0"):
        Table(("a", "b"), ((1,),))
    table = Table.from_csv_text("a,b\n1,x\n2.5,\n")
    assert table.rows == ((1, "x"), (2.5, None))
