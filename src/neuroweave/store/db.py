"""SQLite persistence for runs, node executions, artifacts, provenance and metrics.

SQLite (stdlib) gives transactional writes: a node is only marked SUCCEEDED in the same
transaction that records its output artifacts, so a crash can never leave a "successful"
execution without outputs.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from neuroweave.store.files import utc_now

RunStatus = Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
NodeStatus = Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "SKIPPED", "CANCELLED"]
TERMINAL_RUN_STATES = ("SUCCEEDED", "FAILED", "CANCELLED")

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    workflow_name TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    seed INTEGER NOT NULL,
    use_cache INTEGER NOT NULL,
    trigger TEXT NOT NULL,
    reproduces_run_id TEXT REFERENCES runs(id),
    error TEXT,
    environment TEXT,
    worker_pid INTEGER,
    cancel_requested INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS runs_workflow ON runs(workflow_id, created_at);

CREATE TABLE IF NOT EXISTS node_executions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    node_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    definition_id TEXT NOT NULL,
    definition_version TEXT,
    code_hash TEXT,
    status TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    duration_ms REAL,
    params TEXT NOT NULL DEFAULT '{}',
    seed INTEGER,
    cache_key TEXT,
    cache_hit INTEGER NOT NULL DEFAULT 0,
    cache_source_id TEXT REFERENCES node_executions(id),
    cache_note TEXT,
    error TEXT,
    error_type TEXT,
    traceback TEXT,
    log_path TEXT,
    UNIQUE (run_id, node_id)
);
CREATE INDEX IF NOT EXISTS nx_cache ON node_executions(cache_key, status);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    size INTEGER NOT NULL,
    kind TEXT NOT NULL,
    media_type TEXT NOT NULL,
    serializer TEXT,
    python_type TEXT,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    run_id TEXT REFERENCES runs(id),
    node_execution_id TEXT REFERENCES node_executions(id),
    node_id TEXT,
    port TEXT,
    source_uri TEXT,
    stored INTEGER NOT NULL,
    reused_from TEXT REFERENCES artifacts(id)
);
CREATE INDEX IF NOT EXISTS artifacts_hash ON artifacts(content_hash);
CREATE INDEX IF NOT EXISTS artifacts_producer ON artifacts(node_execution_id);
CREATE INDEX IF NOT EXISTS artifacts_run ON artifacts(run_id);

CREATE TABLE IF NOT EXISTS execution_inputs (
    node_execution_id TEXT NOT NULL REFERENCES node_executions(id),
    port TEXT NOT NULL,
    artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    PRIMARY KEY (node_execution_id, port)
);
CREATE INDEX IF NOT EXISTS inputs_artifact ON execution_inputs(artifact_id);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id),
    node_execution_id TEXT NOT NULL REFERENCES node_executions(id),
    node_id TEXT NOT NULL,
    name TEXT NOT NULL,
    value REAL NOT NULL,
    step INTEGER,
    direction TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS metrics_run ON metrics(run_id);
"""


class RunRecord(BaseModel):
    id: str
    workflow_id: str
    workflow_name: str
    snapshot_hash: str
    status: RunStatus
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    seed: int
    use_cache: bool
    trigger: str
    reproduces_run_id: str | None = None
    error: str | None = None
    environment: dict[str, Any] | None = None
    worker_pid: int | None = None
    cancel_requested: bool = False


class NodeExecutionRecord(BaseModel):
    id: str
    run_id: str
    node_id: str
    ordinal: int
    definition_id: str
    definition_version: str | None = None
    code_hash: str | None = None
    status: NodeStatus = "PENDING"
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: float | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = None
    cache_key: str | None = None
    cache_hit: bool = False
    cache_source_id: str | None = None
    cache_note: str | None = None
    error: str | None = None
    error_type: str | None = None
    traceback: str | None = None
    log_path: str | None = None


class ArtifactRecord(BaseModel):
    id: str
    content_hash: str
    size: int
    kind: str
    media_type: str
    serializer: str | None = None
    python_type: str | None = None
    role: Literal["output", "input"]
    created_at: str
    run_id: str | None = None
    node_execution_id: str | None = None
    node_id: str | None = None
    port: str | None = None
    source_uri: str | None = None
    stored: bool = True
    reused_from: str | None = None


class InputRecord(BaseModel):
    node_execution_id: str
    port: str
    artifact_id: str


class MetricRecord(BaseModel):
    id: int | None = None
    run_id: str
    node_execution_id: str
    node_id: str
    name: str
    value: float
    step: int | None = None
    direction: str | None = None
    created_at: str


_JSON_COLUMNS = {"params", "environment"}
_BOOL_COLUMNS = {"use_cache", "cache_hit", "stored", "cancel_requested"}


def _encode(column: str, value: Any) -> Any:
    if column in _JSON_COLUMNS and value is not None:
        return json.dumps(value, sort_keys=True)
    if column in _BOOL_COLUMNS:
        return int(bool(value))
    return value


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for column in _JSON_COLUMNS & data.keys():
        if data[column] is not None:
            data[column] = json.loads(data[column])
    return data


class Database:
    def __init__(self, path: Path):
        self.path = path
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
                         (str(SCHEMA_VERSION),))

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------ generic helpers

    @staticmethod
    def _insert(conn: sqlite3.Connection, table: str, record: BaseModel,
                exclude: set[str] | None = None) -> None:
        data = record.model_dump(exclude=exclude)
        columns = list(data)
        conn.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
            [_encode(c, data[c]) for c in columns],
        )

    @staticmethod
    def _update(conn: sqlite3.Connection, table: str, key: str, fields: dict[str, Any]) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{c} = ?" for c in fields)
        conn.execute(f"UPDATE {table} SET {assignments} WHERE id = ?",
                     [*(_encode(c, v) for c, v in fields.items()), key])

    # ------------------------------------------------------------------ runs

    def insert_run(self, run: RunRecord) -> None:
        with self.connect() as conn:
            self._insert(conn, "runs", run)

    def update_run(self, run_id: str, **fields: Any) -> None:
        unknown = fields.keys() - RunRecord.model_fields.keys()
        if unknown:
            raise ValueError(f"Unknown run fields: {sorted(unknown)}")
        with self.connect() as conn:
            self._update(conn, "runs", run_id, fields)

    def get_run(self, run_id: str) -> RunRecord | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return RunRecord.model_validate(_decode(row)) if row else None

    def list_runs(self, *, workflow_id: str | None = None, limit: int = 200) -> list[RunRecord]:
        query = "SELECT * FROM runs"
        args: list[Any] = []
        if workflow_id:
            query += " WHERE workflow_id = ?"
            args.append(workflow_id)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        args.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [RunRecord.model_validate(_decode(r)) for r in rows]

    def request_cancel(self, run_id: str) -> None:
        self.update_run(run_id, cancel_requested=True)

    def cancel_requested(self, run_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT cancel_requested FROM runs WHERE id = ?",
                               (run_id,)).fetchone()
        return bool(row and row[0])

    # ------------------------------------------------------------------ node executions

    def insert_node_executions(self, records: list[NodeExecutionRecord]) -> None:
        with self.connect() as conn:
            for record in records:
                self._insert(conn, "node_executions", record)

    def update_node_execution(self, execution_id: str, **fields: Any) -> None:
        unknown = fields.keys() - NodeExecutionRecord.model_fields.keys()
        if unknown:
            raise ValueError(f"Unknown node execution fields: {sorted(unknown)}")
        with self.connect() as conn:
            self._update(conn, "node_executions", execution_id, fields)

    def node_executions(self, run_id: str) -> list[NodeExecutionRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM node_executions WHERE run_id = ? ORDER BY ordinal", (run_id,)
            ).fetchall()
        return [NodeExecutionRecord.model_validate(_decode(r)) for r in rows]

    def get_node_execution(self, execution_id: str) -> NodeExecutionRecord | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM node_executions WHERE id = ?",
                               (execution_id,)).fetchone()
        return NodeExecutionRecord.model_validate(_decode(row)) if row else None

    def find_cache_source(self, cache_key: str) -> NodeExecutionRecord | None:
        """Most recent successful execution with this cache key."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM node_executions WHERE cache_key = ? AND status = 'SUCCEEDED' "
                "ORDER BY finished_at DESC LIMIT 1", (cache_key,)
            ).fetchone()
        return NodeExecutionRecord.model_validate(_decode(row)) if row else None

    def complete_node_execution(
        self, execution_id: str, *, status: NodeStatus, artifacts: list[ArtifactRecord],
        metrics: list[MetricRecord], **fields: Any,
    ) -> None:
        """Record outputs, metrics and the final state atomically."""
        with self.connect() as conn:
            for artifact in artifacts:
                self._insert(conn, "artifacts", artifact)
            for metric in metrics:
                self._insert(conn, "metrics", metric, exclude={"id"})
            self._update(conn, "node_executions", execution_id, {"status": status, **fields})

    # ------------------------------------------------------------------ artifacts

    def insert_artifact(self, artifact: ArtifactRecord) -> None:
        with self.connect() as conn:
            self._insert(conn, "artifacts", artifact)

    def get_artifact(self, artifact_id: str) -> ArtifactRecord | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        return ArtifactRecord.model_validate(_decode(row)) if row else None

    def list_artifacts(
        self, *, run_id: str | None = None, kind: str | None = None, role: str | None = None,
        limit: int = 500,
    ) -> list[ArtifactRecord]:
        clauses, args = [], []
        for column, value in (("run_id", run_id), ("kind", kind), ("role", role)):
            if value is not None:
                clauses.append(f"{column} = ?")
                args.append(value)
        query = "SELECT * FROM artifacts"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC, id LIMIT ?"
        args.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [ArtifactRecord.model_validate(_decode(r)) for r in rows]

    def outputs_of(self, execution_id: str) -> list[ArtifactRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM artifacts WHERE node_execution_id = ? AND role = 'output' "
                "ORDER BY port", (execution_id,)
            ).fetchall()
        return [ArtifactRecord.model_validate(_decode(r)) for r in rows]

    def artifacts_with_hash(self, content_hash: str) -> list[ArtifactRecord]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM artifacts WHERE content_hash = ? ORDER BY "
                                "created_at", (content_hash,)).fetchall()
        return [ArtifactRecord.model_validate(_decode(r)) for r in rows]

    # ------------------------------------------------------------------ provenance

    def insert_inputs(self, inputs: list[InputRecord]) -> None:
        with self.connect() as conn:
            for record in inputs:
                self._insert(conn, "execution_inputs", record)

    def inputs_of(self, execution_id: str) -> list[InputRecord]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM execution_inputs WHERE node_execution_id = ? "
                                "ORDER BY port", (execution_id,)).fetchall()
        return [InputRecord.model_validate(dict(r)) for r in rows]

    def consumers_of(self, artifact_id: str) -> list[InputRecord]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM execution_inputs WHERE artifact_id = ? "
                                "ORDER BY node_execution_id", (artifact_id,)).fetchall()
        return [InputRecord.model_validate(dict(r)) for r in rows]

    # ------------------------------------------------------------------ metrics

    def metrics_for_run(self, run_id: str) -> list[MetricRecord]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM metrics WHERE run_id = ? ORDER BY id",
                                (run_id,)).fetchall()
        return [MetricRecord.model_validate(dict(r)) for r in rows]

    # ------------------------------------------------------------------ recovery

    def reconcile_stale_runs(self, is_alive: Callable[[int], bool]) -> list[str]:
        """Close out runs whose worker process died without recording a final state."""
        repaired: list[str] = []
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, worker_pid, cancel_requested, status FROM runs "
                "WHERE status IN ('PENDING', 'RUNNING')"
            ).fetchall()
        for row in rows:
            pid = row["worker_pid"]
            if pid is None or is_alive(pid):
                continue
            cancelled = bool(row["cancel_requested"])
            now = utc_now()
            with self.connect() as conn:
                conn.execute(
                    "UPDATE node_executions SET status = ?, finished_at = ?, error = "
                    "COALESCE(error, ?) WHERE run_id = ? AND status = 'RUNNING'",
                    ("CANCELLED" if cancelled else "FAILED", now,
                     "Worker process exited while this node was running.", row["id"]),
                )
                conn.execute(
                    "UPDATE node_executions SET status = ? WHERE run_id = ? AND status = "
                    "'PENDING'", ("CANCELLED" if cancelled else "SKIPPED", row["id"]),
                )
                conn.execute(
                    "UPDATE runs SET status = ?, finished_at = ?, error = COALESCE(error, ?) "
                    "WHERE id = ?",
                    ("CANCELLED" if cancelled else "FAILED", now,
                     "Run cancelled; worker terminated." if cancelled else
                     "Worker process exited unexpectedly before the run finished.", row["id"]),
                )
            repaired.append(row["id"])
        return repaired
