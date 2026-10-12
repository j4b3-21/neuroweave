"""Sequential, dependency-ordered execution of a workflow snapshot.

State machine
-------------
Run:  PENDING -> RUNNING -> SUCCEEDED | FAILED | CANCELLED
Node: PENDING -> RUNNING -> SUCCEEDED | FAILED | CANCELLED
      PENDING -> SKIPPED    (an upstream node did not succeed)
      PENDING -> CANCELLED  (the run was cancelled before the node started)

Guarantees
----------
* A node only runs when every upstream node SUCCEEDED; a failure never yields a downstream
  success.
* Node inputs are always loaded from the artifact store (hash-verified), never passed as
  in-memory objects, so what provenance records is exactly what the node consumed.
* Outputs, metrics and the SUCCEEDED state are committed in one SQLite transaction.

Execution is in-process and *not* sandboxed: workflows run arbitrary Python with the
user's privileges. Only run node code you trust.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import random
import sys
import time
import traceback
from collections.abc import Callable, Iterator
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from neuroweave.kernel.definitions import NodeDefinition, PortSpec
from neuroweave.kernel.model import NodeInstance, Workflow
from neuroweave.kernel.validation import validate_workflow
from neuroweave.runtime.cache import cache_key
from neuroweave.runtime.environment import capture_environment
from neuroweave.runtime.typecheck import describe, matches
from neuroweave.sdk.context import MetricEntry, NodeContext, _current
from neuroweave.sdk.introspection import RegisteredNode
from neuroweave.sdk.registry import ModuleLoadError, NodeRegistry, default_registry
from neuroweave.store.artifacts import (
    ArtifactIntegrityError,
    deserialize,
    guess_media_type,
    hash_file,
    serialize,
)
from neuroweave.store.db import (
    ArtifactRecord,
    InputRecord,
    MetricRecord,
    NodeExecutionRecord,
    RunRecord,
)
from neuroweave.store.files import new_id, new_run_id, utc_now
from neuroweave.store.workspace import Workspace


class RunCancelled(BaseException):
    """Raised inside a node to abort it. BaseException so user ``except Exception`` blocks
    cannot swallow a cancellation."""


@dataclass
class CancellationState:
    in_node: bool = False
    requested: bool = False


cancellation = CancellationState()


@dataclass
class RunEvent:
    kind: str
    run_id: str
    node_id: str | None = None
    status: str | None = None
    message: str | None = None


EventHandler = Callable[[RunEvent], None]


# ---------------------------------------------------------------------------- public API


def prepare_run(
    workspace: Workspace,
    workflow: Workflow,
    *,
    seed: int | None = None,
    use_cache: bool = True,
    trigger: str = "cli",
    reproduces_run_id: str | None = None,
) -> RunRecord:
    """Freeze the workflow as an immutable snapshot and create a PENDING run record."""
    snapshot = workspace.write_snapshot(workflow)
    run = RunRecord(
        id=new_run_id(),
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        snapshot_hash=snapshot,
        status="PENDING",
        created_at=utc_now(),
        seed=workspace.config.default_seed if seed is None else seed,
        use_cache=use_cache,
        trigger=trigger,
        reproduces_run_id=reproduces_run_id,
    )
    workspace.db.insert_run(run)
    return run


def execute_run(
    workspace: Workspace,
    run_id: str,
    registry: NodeRegistry | None = None,
    *,
    on_event: EventHandler | None = None,
    module_errors: list[ModuleLoadError] | None = None,
) -> RunRecord:
    """Execute a PENDING run. Returns the final run record."""
    registry = default_registry if registry is None else registry
    db = workspace.db
    run = db.get_run(run_id)
    if run is None:
        raise KeyError(f"Run '{run_id}' does not exist.")
    if run.status != "PENDING":
        raise RuntimeError(f"Run '{run_id}' is {run.status}; only PENDING runs can execute.")

    emit = on_event or (lambda event: None)
    db.update_run(run_id, status="RUNNING", started_at=utc_now(), worker_pid=os.getpid(),
                  environment=capture_environment(workspace.root, workspace.artifacts))
    emit(RunEvent("run_started", run_id))
    status, error = "FAILED", None
    try:
        workflow = workspace.load_snapshot(run.snapshot_hash)
        report = validate_workflow(workflow, registry.catalog())
        if not report.valid:
            problems = "; ".join(i.message for i in report.errors)
            if module_errors:
                problems += " | Node module import errors: " + "; ".join(
                    f"{e.module}: {e.error}" for e in module_errors)
            error = f"Workflow validation failed: {problems}"
        else:
            with contextlib.chdir(workspace.root):
                status, error = _RunExecutor(workspace, run, workflow, registry, report.order,
                                             emit).execute()
    except Exception as exc:  # internal failure: record it rather than leave RUNNING
        error = f"Internal error: {type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        status = "FAILED"
    db.update_run(run_id, status=status, finished_at=utc_now(), error=error)
    emit(RunEvent("run_finished", run_id, status=status, message=error))
    final = db.get_run(run_id)
    assert final is not None
    return final


def run_workflow(
    workspace: Workspace,
    workflow: Workflow,
    registry: NodeRegistry | None = None,
    *,
    seed: int | None = None,
    use_cache: bool = True,
    trigger: str = "cli",
    reproduces_run_id: str | None = None,
    on_event: EventHandler | None = None,
) -> RunRecord:
    run = prepare_run(workspace, workflow, seed=seed, use_cache=use_cache, trigger=trigger,
                      reproduces_run_id=reproduces_run_id)
    return execute_run(workspace, run.id, registry, on_event=on_event)


def derive_seed(run_seed: int, node_id: str) -> int:
    digest = hashlib.sha256(f"{run_seed}:{node_id}".encode()).hexdigest()
    return int(digest[:8], 16)


def load_artifact_value(workspace: Workspace, artifact: ArtifactRecord) -> Any:
    if not artifact.stored or artifact.serializer is None:
        raise ArtifactIntegrityError(f"Artifact {artifact.id} has no stored value to load.")
    data = workspace.artifacts.get_bytes(artifact.content_hash, verify=True)
    return deserialize(data, artifact.serializer)


# ---------------------------------------------------------------------------- internals


@dataclass
class _Resolved:
    from_artifacts: dict[str, ArtifactRecord] = field(default_factory=dict)
    literals: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    param_reprs: dict[str, str] = field(default_factory=dict)
    inputs: list[InputRecord] = field(default_factory=list)
    input_hashes: dict[str, str] = field(default_factory=dict)


class NodeFailure(Exception):
    """A user-facing node error (bad input, wrong output shape) without a library traceback."""


def _is_file_port(port: PortSpec) -> bool:
    spec = port.type.args[0] if port.type.kind == "optional" else port.type
    return spec.kind == "file"


@contextlib.contextmanager
def _capture_output(path: Path) -> Iterator[Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", buffering=1) as handle:
        handler = logging.StreamHandler(handle)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            with redirect_stdout(handle), redirect_stderr(handle):
                yield handle
        finally:
            root.removeHandler(handler)


@contextlib.contextmanager
def _node_scope(context: NodeContext) -> Iterator[None]:
    token = _current.set(context)
    cancellation.in_node = True
    try:
        if cancellation.requested:
            raise RunCancelled()
        yield
    finally:
        cancellation.in_node = False
        _current.reset(token)


def _seed_generators(seed: int) -> None:
    random.seed(seed)
    numpy = sys.modules.get("numpy")
    if numpy is not None:
        numpy.random.seed(seed % (2**32))


class _RunExecutor:
    def __init__(self, workspace: Workspace, run: RunRecord, workflow: Workflow,
                 registry: NodeRegistry, order: list[str], emit: EventHandler):
        self.ws = workspace
        self.db = workspace.db
        self.run = run
        self.workflow = workflow
        self.registry = registry
        self.order = order
        self.emit = emit
        self.outputs: dict[tuple[str, str], ArtifactRecord] = {}
        self.max_snapshot = workspace.config.max_input_snapshot_bytes

    def _cancel_requested(self) -> bool:
        return cancellation.requested or self.db.cancel_requested(self.run.id)

    def execute(self) -> tuple[str, str | None]:
        records: dict[str, NodeExecutionRecord] = {}
        for ordinal, node_id in enumerate(self.order):
            instance = self.workflow.node(node_id)
            assert instance is not None
            definition = self.registry.get(instance.type).definition
            records[node_id] = NodeExecutionRecord(
                id=new_id("nx"), run_id=self.run.id, node_id=node_id, ordinal=ordinal,
                definition_id=definition.id, definition_version=definition.version,
                code_hash=definition.code_hash,
            )
        self.db.insert_node_executions(list(records.values()))

        status_of: dict[str, str] = {}
        cancelled = False
        for node_id in self.order:
            record = records[node_id]
            if cancelled or self._cancel_requested():
                cancelled = True
                self.db.update_node_execution(record.id, status="CANCELLED",
                                              error="Run was cancelled before this node started.")
                status_of[node_id] = "CANCELLED"
                continue
            blocked = sorted({e.source for e in self.workflow.incoming(node_id)
                              if status_of.get(e.source) != "SUCCEEDED"})
            if blocked:
                self.db.update_node_execution(
                    record.id, status="SKIPPED",
                    error=f"Skipped because upstream node(s) {', '.join(blocked)} did not "
                          "succeed.")
                status_of[node_id] = "SKIPPED"
                self.emit(RunEvent("node_finished", self.run.id, node_id, "SKIPPED"))
                continue
            instance = self.workflow.node(node_id)
            assert instance is not None
            try:
                status_of[node_id] = self._execute_node(instance, record)
            except RunCancelled:
                status_of[node_id] = "CANCELLED"
                cancelled = True

        if cancelled:
            return "CANCELLED", "Run cancelled by user."
        failed = [n for n in self.order if status_of[n] == "FAILED"]
        if failed:
            return "FAILED", f"Node(s) failed: {', '.join(failed)}."
        return "SUCCEEDED", None

    # ------------------------------------------------------------------ one node

    def _execute_node(self, instance: NodeInstance, record: NodeExecutionRecord) -> str:
        registered = self.registry.get(instance.type)
        definition = registered.definition
        log_path = self.ws.run_dir(self.run.id) / "logs" / f"{instance.id}.log"
        started = time.perf_counter()
        seed = derive_seed(self.run.seed, instance.id)
        self.db.update_node_execution(
            record.id, status="RUNNING", started_at=utc_now(), seed=seed,
            log_path=str(log_path.relative_to(self.ws.dir)),
        )
        self.emit(RunEvent("node_started", self.run.id, instance.id, "RUNNING"))
        context = NodeContext(run_id=self.run.id, node_id=instance.id,
                              node_execution_id=record.id, seed=seed,
                              project_root=self.ws.root)

        def finish(status: str, artifacts: list[ArtifactRecord], **fields: Any) -> str:
            metrics = [
                MetricRecord(run_id=self.run.id, node_execution_id=record.id,
                             node_id=instance.id, name=m.name, value=m.value, step=m.step,
                             direction=m.direction, created_at=utc_now())
                for m in context.metrics
            ]
            self.db.complete_node_execution(
                record.id, status=status, artifacts=artifacts, metrics=metrics,
                finished_at=utc_now(),
                duration_ms=round((time.perf_counter() - started) * 1000, 3), **fields)
            self.emit(RunEvent("node_finished", self.run.id, instance.id, status,
                               fields.get("error")))
            return status

        try:
            resolved = self._resolve_inputs(instance, definition, record)
            self.db.insert_inputs(resolved.inputs)
            recorded_params = {**resolved.params, **resolved.param_reprs}
            key, note = cache_key(definition, resolved.params, resolved.input_hashes, seed)
            self.db.update_node_execution(record.id, params=recorded_params, cache_key=key,
                                          cache_note=note)
            if key and self.run.use_cache:
                reused = self._reuse_cached(record, instance, definition, key, log_path)
                if reused is not None:
                    artifacts, source_id, metrics = reused
                    context.metrics.extend(metrics)
                    for artifact in artifacts:
                        self.outputs[(instance.id, artifact.port or "")] = artifact
                    return finish("SUCCEEDED", artifacts, cache_hit=True,
                                  cache_source_id=source_id,
                                  cache_note=f"Reused result of execution {source_id}.")
            elif key and not self.run.use_cache:
                self.db.update_node_execution(record.id,
                                              cache_note="caching disabled for this run")

            kwargs = self._materialize(resolved)
            self._check_inputs(registered, kwargs)
            _seed_generators(seed)
            with _capture_output(log_path), _node_scope(context):
                result = registered.func(**kwargs)
            values = self._split_outputs(registered, result)
            artifacts = [self._store_output(record, instance, port, value)
                         for port, value in values.items()]
            for artifact in artifacts:
                self.outputs[(instance.id, artifact.port or "")] = artifact
            return finish("SUCCEEDED", artifacts)
        except (RunCancelled, KeyboardInterrupt):
            finish("CANCELLED", [], error="Cancelled while running.")
            raise RunCancelled() from None
        except (Exception, SystemExit) as exc:
            details = traceback.format_exc()
            with contextlib.suppress(OSError):
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(log_path, "a", encoding="utf-8") as handle:
                    handle.write(details)
            message = f"{type(exc).__name__}: {exc}"
            return finish("FAILED", [], error=message, error_type=type(exc).__name__,
                          traceback=None if isinstance(exc, NodeFailure) else details)

    def _resolve_inputs(self, instance: NodeInstance, definition: NodeDefinition,
                        record: NodeExecutionRecord) -> _Resolved:
        resolved = _Resolved()
        incoming = {e.target_port: e for e in self.workflow.incoming(instance.id)}
        for port in definition.inputs:
            edge = incoming.get(port.name)
            if edge is not None:
                artifact = self.outputs[(edge.source, edge.source_port)]
                resolved.from_artifacts[port.name] = artifact
                resolved.inputs.append(InputRecord(node_execution_id=record.id, port=port.name,
                                                   artifact_id=artifact.id))
                resolved.input_hashes[port.name] = f"{artifact.serializer}:{artifact.content_hash}"
            elif port.name in instance.params:
                value = instance.params[port.name]
                resolved.params[port.name] = value
                if _is_file_port(port) and value is not None:
                    path = self._resolve_path(value, instance.id, port.name)
                    artifact = self._record_external_input(path, record)
                    resolved.inputs.append(InputRecord(node_execution_id=record.id,
                                                       port=port.name, artifact_id=artifact.id))
                    resolved.input_hashes[port.name] = f"file:{artifact.content_hash}"
                    resolved.literals[port.name] = path
                else:
                    resolved.literals[port.name] = value
            elif port.has_default:
                if port.default_repr is None:
                    resolved.params[port.name] = port.default
                else:
                    resolved.param_reprs[port.name] = port.default_repr
            else:
                raise NodeFailure(f"Required input '{port.name}' has no value.")
        return resolved

    def _resolve_path(self, value: str, node_id: str, port: str) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self.ws.root / path
        if not path.exists():
            raise NodeFailure(f"Input '{port}' of '{node_id}': file not found: {path}")
        return path

    def _record_external_input(self, path: Path, record: NodeExecutionRecord) -> ArtifactRecord:
        store = self.ws.artifacts
        if path.is_dir():
            manifest = []
            for child in sorted(p for p in path.rglob("*") if p.is_file()):
                manifest.append({"path": child.relative_to(path).as_posix(),
                                 "sha256": hash_file(child), "size": child.stat().st_size})
            data = json.dumps(manifest, sort_keys=True).encode("utf-8")
            content_hash, size = store.put_bytes(data)
            kind, media_type, stored = "directory", "application/json", True
        else:
            size = path.stat().st_size
            if size <= self.max_snapshot:
                content_hash, size = store.put_bytes(path.read_bytes())
                stored = True
            else:
                content_hash, stored = hash_file(path), False
            kind, media_type = "file", guess_media_type(path)
        try:
            source = path.resolve().relative_to(self.ws.root).as_posix()
        except ValueError:
            source = str(path.resolve())
        artifact = ArtifactRecord(
            id=new_id("art"), content_hash=content_hash, size=size, kind=kind,
            media_type=media_type, serializer=None, python_type=None, role="input",
            created_at=utc_now(), run_id=self.run.id, node_id=record.node_id,
            source_uri=source, stored=stored,
        )
        self.db.insert_artifact(artifact)
        return artifact

    def _materialize(self, resolved: _Resolved) -> dict[str, Any]:
        kwargs = dict(resolved.literals)
        for port, artifact in resolved.from_artifacts.items():
            kwargs[port] = load_artifact_value(self.ws, artifact)
        return kwargs

    def _check_inputs(self, registered: RegisteredNode, kwargs: dict[str, Any]) -> None:
        for name, value in kwargs.items():
            annotation = registered.input_annotations.get(name)
            if annotation is not None and not matches(value, annotation):
                raise NodeFailure(f"Input '{name}' expected {describe(annotation)} but received "
                                  f"{type(value).__name__}.")

    def _split_outputs(self, registered: RegisteredNode, result: Any) -> dict[str, Any]:
        ports = [p.name for p in registered.definition.outputs]
        if not ports:
            return {}
        if ports == ["output"]:
            values = {"output": result}
        elif isinstance(result, dict):
            if set(result) != set(ports):
                raise NodeFailure(f"Node must return keys {ports}, returned {sorted(result)}.")
            values = {p: result[p] for p in ports}
        elif isinstance(result, (tuple, list)) and len(result) == len(ports):
            values = dict(zip(ports, result, strict=True))
        else:
            raise NodeFailure(f"Node declares outputs {ports}; return a dict with those keys "
                              f"or a tuple of {len(ports)} values.")
        for port, value in values.items():
            annotation = registered.output_annotations.get(port)
            if annotation is not None and not matches(value, annotation):
                raise NodeFailure(f"Output '{port}' expected {describe(annotation)} but the "
                                  f"node returned {type(value).__name__}.")
        return values

    def _store_output(self, record: NodeExecutionRecord, instance: NodeInstance, port: str,
                      value: Any) -> ArtifactRecord:
        serialized = serialize(value)
        content_hash, size = self.ws.artifacts.put_bytes(serialized.data)
        return ArtifactRecord(
            id=new_id("art"), content_hash=content_hash, size=size, kind=serialized.kind,
            media_type=serialized.media_type, serializer=serialized.serializer,
            python_type=serialized.python_type, role="output", created_at=utc_now(),
            run_id=self.run.id, node_execution_id=record.id, node_id=instance.id, port=port,
        )

    def _reuse_cached(
        self, record: NodeExecutionRecord, instance: NodeInstance, definition: NodeDefinition,
        key: str, log_path: Path,
    ) -> tuple[list[ArtifactRecord], str, list[Any]] | None:
        source = self.db.find_cache_source(key)
        if source is None:
            return None
        previous = self.db.outputs_of(source.id)
        if {a.port for a in previous} != {p.name for p in definition.outputs}:
            return None
        if not all(self.ws.artifacts.verify(a.content_hash) for a in previous):
            self.db.update_node_execution(
                record.id, cache_note="cached result failed integrity verification; recomputed")
            return None
        origin = source.cache_source_id or source.id
        artifacts = [
            a.model_copy(update={"id": new_id("art"), "run_id": self.run.id,
                                 "node_execution_id": record.id, "node_id": instance.id,
                                 "created_at": utc_now(), "reused_from": a.id})
            for a in previous
        ]
        metrics = [MetricEntry(m.name, m.value, m.step, m.direction)  # type: ignore[arg-type]
                   for m in self.db.metrics_for_run(source.run_id)
                   if m.node_execution_id == source.id]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(f"[neuroweave] Reused cached result of node execution {origin} "
                         f"(cache key {key[:12]}…); the function was not re-executed.\n")
        return artifacts, origin, metrics
