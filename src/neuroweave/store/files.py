"""Atomic file writes and identifier helpers."""

from __future__ import annotations

import os
import re
import secrets
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` so readers see either the old or the complete new file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def new_run_id() -> str:
    return "run_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "_" + secrets.token_hex(3)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


RUN_ID_PATTERN = re.compile(r"^run_[0-9]{8}T[0-9]{6}_[0-9a-f]{6}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
