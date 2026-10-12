"""HTTP API for NeuroWeave Studio.

Security model: a single-user, local tool. The server binds to loopback, rejects requests
whose Host header is not local (DNS-rebinding protection) and requires the
``X-NeuroWeave-Client`` header on state-changing requests. Browsers cannot attach custom
headers cross-origin without a CORS preflight, which this server never approves, so other
websites cannot trigger runs. There is no authentication: anyone with local access to the
port can execute the project's node code.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from neuroweave import __version__
from neuroweave.experiments import RunComparison, compare_runs, reproduction_report
from neuroweave.kernel.model import WORKFLOW_ID_PATTERN, Workflow
from neuroweave.kernel.serialization import snapshot_hash as workflow_revision
from neuroweave.kernel.validation import ValidationReport, validate_workflow
from neuroweave.provenance import Lineage, downstream_lineage, upstream_lineage
from neuroweave.server.services import Catalog, CatalogService, RunManager, tail
from neuroweave.store.artifacts import TEXT_MEDIA_TYPES, ArtifactIntegrityError
from neuroweave.store.db import ArtifactRecord, MetricRecord, NodeExecutionRecord, RunRecord
from neuroweave.store.workspace import WorkflowNotFoundError, Workspace

STATIC_DIR = Path(__file__).parent / "static"
CLIENT_HEADER = "x-neuroweave-client"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
PREVIEW_LIMIT = 2_000_000


class ProjectInfo(BaseModel):
    name: str
    root: str
    node_modules: list[str]
    default_seed: int
    version: str
    workflow_count: int
    run_count: int


class ProjectUpdate(BaseModel):
    name: str | None = None
    node_modules: list[str] | None = None
    default_seed: int | None = None


class WorkflowCreate(BaseModel):
    id: str = Field(pattern=WORKFLOW_ID_PATTERN)
    name: str = Field(min_length=1)
    description: str = ""


class WorkflowSummary(BaseModel):
    id: str
    name: str
    description: str
    node_count: int
    edge_count: int
    last_run: RunRecord | None = None


class SavedWorkflow(BaseModel):
    workflow: Workflow
    validation: ValidationReport
    revision: str


class RunRequest(BaseModel):
    seed: int | None = None
    use_cache: bool = True


class NodeExecutionDetail(BaseModel):
    execution: NodeExecutionRecord
    inputs: dict[str, ArtifactRecord]
    outputs: list[ArtifactRecord]


class RunDetail(BaseModel):
    run: RunRecord
    workflow: Workflow
    nodes: list[NodeExecutionDetail]
    metrics: list[MetricRecord]


class ArtifactDetail(BaseModel):
    artifact: ArtifactRecord
    previewable: bool
    producer: NodeExecutionRecord | None
    consumers: list[NodeExecutionRecord]


class VerifyResult(BaseModel):
    artifact_id: str
    content_hash: str
    stored: bool
    ok: bool
    message: str


def _hostname(header: str) -> str:
    """Strip the port from a Host header value (handles bracketed IPv6)."""
    if header.startswith("["):
        return header.split("]", 1)[0] + "]"
    return header.rsplit(":", 1)[0] if header.count(":") == 1 else header


def create_app(project_root: Path, *, allowed_hosts_extra: list[str] | tuple[str, ...] = ()
               ) -> FastAPI:
    workspace = Workspace(project_root)
    catalog = CatalogService(workspace)
    runs = RunManager(workspace)
    allowed_hosts = LOCAL_HOSTS | set(allowed_hosts_extra)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        runs.poll()
        yield
        runs.shutdown()

    app = FastAPI(title="NeuroWeave", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.workspace = workspace
    app.state.runs = runs
    app.state.catalog = catalog

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if _hostname(request.headers.get("host", "")) not in allowed_hosts:
            return JSONResponse({"detail": "Host not allowed."}, status_code=403)
        if (request.method not in ("GET", "HEAD", "OPTIONS")
                and request.url.path.startswith("/api/")
                and request.headers.get(CLIENT_HEADER) is None):
            return JSONResponse(
                {"detail": f"Missing {CLIENT_HEADER} header on state-changing request."},
                status_code=403)
        return await call_next(request)

    def not_found(message: str) -> HTTPException:
        return HTTPException(status_code=404, detail=message)

    def get_run_or_404(run_id: str) -> RunRecord:
        runs.poll()
        record = workspace.db.get_run(run_id)
        if record is None:
            raise not_found(f"Run '{run_id}' does not exist.")
        return record

    def get_artifact_or_404(artifact_id: str) -> ArtifactRecord:
        record = workspace.db.get_artifact(artifact_id)
        if record is None:
            raise not_found(f"Artifact '{artifact_id}' does not exist.")
        return record

    def load_workflow_or_404(workflow_id: str) -> Workflow:
        try:
            return workspace.load_workflow(workflow_id)
        except WorkflowNotFoundError:
            raise not_found(f"Workflow '{workflow_id}' does not exist.") from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    def validate(workflow: Workflow) -> ValidationReport:
        return validate_workflow(workflow, catalog.get().by_id())

    # ------------------------------------------------------------------ project

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    def project_info() -> ProjectInfo:
        config = workspace.config
        return ProjectInfo(
            name=config.name, root=str(workspace.root), node_modules=config.node_modules,
            default_seed=config.default_seed, version=__version__,
            workflow_count=len(workspace.list_workflows()),
            run_count=len(workspace.db.list_runs(limit=1_000_000)),
        )

    @app.get("/api/project", response_model=ProjectInfo)
    def get_project() -> ProjectInfo:
        return project_info()

    @app.put("/api/project", response_model=ProjectInfo)
    def update_project(update: ProjectUpdate) -> ProjectInfo:
        config = workspace.config
        for field, value in update.model_dump(exclude_none=True).items():
            setattr(config, field, value)
        workspace.save_config(config)
        return project_info()

    @app.get("/api/nodes", response_model=Catalog)
    def get_nodes(refresh: bool = False) -> Catalog:
        return catalog.get(refresh=refresh)

    # ------------------------------------------------------------------ workflows

    @app.get("/api/workflows", response_model=list[WorkflowSummary])
    def list_workflows() -> list[WorkflowSummary]:
        runs.poll()
        result = []
        for workflow in workspace.list_workflows():
            recent = workspace.db.list_runs(workflow_id=workflow.id, limit=1)
            result.append(WorkflowSummary(
                id=workflow.id, name=workflow.name, description=workflow.description,
                node_count=len(workflow.nodes), edge_count=len(workflow.edges),
                last_run=recent[0] if recent else None))
        return result

    @app.post("/api/workflows", response_model=Workflow, status_code=201)
    def create_workflow(request: WorkflowCreate) -> Workflow:
        if workspace.workflow_exists(request.id):
            raise HTTPException(status_code=409, detail=f"Workflow '{request.id}' exists.")
        workflow = Workflow(id=request.id, name=request.name, description=request.description)
        workspace.save_workflow(workflow)
        return workflow

    @app.get("/api/workflows/{workflow_id}", response_model=Workflow)
    def get_workflow(workflow_id: str, response: Response) -> Workflow:
        workflow = load_workflow_or_404(workflow_id)
        response.headers["ETag"] = f'"{workflow_revision(workflow)}"'
        return workflow

    @app.put("/api/workflows/{workflow_id}", response_model=SavedWorkflow)
    def save_workflow(workflow_id: str, workflow: Workflow,
                      if_match: str | None = Header(default=None)) -> SavedWorkflow:
        """Save a workflow. With ``If-Match``, the save is refused (409) when the stored
        version is no longer the one the client edited, so concurrent editors (another Studio
        tab, ``nw workflows import --force``) never silently overwrite each other."""
        if workflow.id != workflow_id:
            raise HTTPException(status_code=400, detail="Workflow id in body does not match URL.")
        if if_match is not None and workspace.workflow_exists(workflow_id):
            current = workflow_revision(load_workflow_or_404(workflow_id))
            if if_match.strip().strip('"') != current:
                raise HTTPException(status_code=409, detail={
                    "message": "This workflow was changed elsewhere (another Studio tab or the "
                               "CLI) after you opened it. Your latest edit was not saved.",
                    "revision": current})
        workspace.save_workflow(workflow)
        return SavedWorkflow(workflow=workflow, validation=validate(workflow),
                             revision=workflow_revision(workflow))

    @app.delete("/api/workflows/{workflow_id}", status_code=204)
    def delete_workflow(workflow_id: str) -> Response:
        try:
            workspace.delete_workflow(workflow_id)
        except WorkflowNotFoundError:
            raise not_found(f"Workflow '{workflow_id}' does not exist.") from None
        return Response(status_code=204)

    @app.post("/api/workflows/{workflow_id}/validate", response_model=ValidationReport)
    def validate_endpoint(workflow_id: str, workflow: Workflow | None = None) -> ValidationReport:
        return validate(workflow or load_workflow_or_404(workflow_id))

    @app.post("/api/workflows/{workflow_id}/runs", response_model=RunRecord, status_code=202)
    def start_run(workflow_id: str, request: RunRequest) -> RunRecord:
        workflow = load_workflow_or_404(workflow_id)
        report = validate(workflow)
        if not report.valid:
            raise HTTPException(status_code=422, detail={
                "message": "Workflow is invalid; nothing was executed.",
                "validation": report.model_dump(mode="json")})
        return runs.start(workflow, seed=request.seed, use_cache=request.use_cache)

    # ------------------------------------------------------------------ runs

    @app.get("/api/runs", response_model=list[RunRecord])
    def list_runs(workflow_id: str | None = None,
                  limit: int = Query(100, ge=1, le=1000)) -> list[RunRecord]:
        runs.poll()
        return workspace.db.list_runs(workflow_id=workflow_id, limit=limit)

    @app.get("/api/runs/{run_id}", response_model=RunDetail)
    def get_run(run_id: str) -> RunDetail:
        record = get_run_or_404(run_id)
        db = workspace.db
        nodes = []
        for execution in db.node_executions(run_id):
            inputs = {}
            for item in db.inputs_of(execution.id):
                artifact = db.get_artifact(item.artifact_id)
                if artifact is not None:
                    inputs[item.port] = artifact
            nodes.append(NodeExecutionDetail(execution=execution, inputs=inputs,
                                             outputs=db.outputs_of(execution.id)))
        return RunDetail(run=record, workflow=workspace.load_snapshot(record.snapshot_hash),
                         nodes=nodes, metrics=db.metrics_for_run(run_id))

    @app.get("/api/runs/{run_id}/logs/{node_id}", response_class=PlainTextResponse)
    def get_logs(run_id: str, node_id: str) -> str:
        get_run_or_404(run_id)
        execution = next((e for e in workspace.db.node_executions(run_id)
                          if e.node_id == node_id), None)
        if execution is None:
            raise not_found(f"Run '{run_id}' has no node '{node_id}'.")
        if not execution.log_path:
            return ""
        path = (workspace.dir / execution.log_path).resolve()
        if workspace.dir.resolve() not in path.parents:
            raise HTTPException(status_code=400, detail="Invalid log path.")
        return tail(path)

    @app.get("/api/runs/{run_id}/worker-log", response_class=PlainTextResponse)
    def get_worker_log(run_id: str) -> str:
        get_run_or_404(run_id)
        return tail(workspace.run_dir(run_id) / "worker.log")

    @app.post("/api/runs/{run_id}/cancel", response_model=RunRecord)
    def cancel_run(run_id: str) -> RunRecord:
        get_run_or_404(run_id)
        record = runs.cancel(run_id)
        assert record is not None
        return record

    @app.post("/api/runs/{run_id}/reproduce", response_model=RunRecord, status_code=202)
    def reproduce(run_id: str) -> RunRecord:
        original = get_run_or_404(run_id)
        if original.status not in ("SUCCEEDED", "FAILED"):
            raise HTTPException(status_code=409, detail="Only finished runs can be reproduced.")
        workflow = workspace.load_snapshot(original.snapshot_hash)
        return runs.start(workflow, seed=original.seed, use_cache=False, trigger="reproduce",
                          reproduces_run_id=original.id)

    @app.get("/api/runs/{run_id}/reproduction")
    def reproduction(run_id: str) -> dict[str, Any]:
        get_run_or_404(run_id)
        try:
            return reproduction_report(workspace, run_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc).strip("'\"")) from None

    @app.get("/api/compare", response_model=RunComparison)
    def compare(a: str, b: str) -> RunComparison:
        get_run_or_404(a)
        get_run_or_404(b)
        return compare_runs(workspace, a, b)

    @app.get("/api/snapshots/{snapshot_hash}", response_model=Workflow)
    def get_snapshot(snapshot_hash: str) -> Workflow:
        try:
            return workspace.load_snapshot(snapshot_hash)
        except (FileNotFoundError, ValueError) as exc:
            raise not_found(str(exc)) from None

    # ------------------------------------------------------------------ artifacts

    @app.get("/api/artifacts", response_model=list[ArtifactRecord])
    def list_artifacts(run_id: str | None = None, kind: str | None = None,
                       role: Literal["input", "output"] | None = None,
                       limit: int = Query(200, ge=1, le=5000)) -> list[ArtifactRecord]:
        return workspace.db.list_artifacts(run_id=run_id, kind=kind, role=role, limit=limit)

    @app.get("/api/artifacts/{artifact_id}", response_model=ArtifactDetail)
    def get_artifact(artifact_id: str) -> ArtifactDetail:
        artifact = get_artifact_or_404(artifact_id)
        db = workspace.db
        producer = db.get_node_execution(artifact.node_execution_id) \
            if artifact.node_execution_id else None
        consumers = [e for e in (db.get_node_execution(c.node_execution_id)
                                 for c in db.consumers_of(artifact_id)) if e is not None]
        return ArtifactDetail(
            artifact=artifact, producer=producer, consumers=consumers,
            previewable=artifact.stored and artifact.media_type in TEXT_MEDIA_TYPES
            and artifact.size <= PREVIEW_LIMIT)

    @app.get("/api/artifacts/{artifact_id}/content")
    def get_artifact_content(artifact_id: str, download: bool = False) -> Response:
        artifact = get_artifact_or_404(artifact_id)
        if not artifact.stored:
            raise HTTPException(status_code=404, detail="This input was recorded by hash only; "
                                "its bytes are not in the artifact store.")
        try:
            data = workspace.artifacts.get_bytes(artifact.content_hash, verify=True)
        except ArtifactIntegrityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        headers = {
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
                                       "img-src data:; sandbox",
            "X-Content-SHA256": artifact.content_hash,
        }
        textual = artifact.media_type in TEXT_MEDIA_TYPES
        if download or not textual:
            suffix = {"application/json": ".json", "image/svg+xml": ".svg",
                      "text/markdown": ".md", "text/plain": ".txt",
                      "application/vnd.neuroweave.table+json": ".table.json",
                      "application/vnd.python.pickle": ".pkl"}.get(artifact.media_type, "")
            headers["Content-Disposition"] = f'attachment; filename="{artifact.id}{suffix}"'
        return Response(content=data, media_type=artifact.media_type, headers=headers)

    @app.post("/api/artifacts/{artifact_id}/verify", response_model=VerifyResult)
    def verify_artifact(artifact_id: str) -> VerifyResult:
        artifact = get_artifact_or_404(artifact_id)
        if not artifact.stored:
            return VerifyResult(artifact_id=artifact_id, content_hash=artifact.content_hash,
                                stored=False, ok=False,
                                message="Bytes were not stored (hash-only input); nothing to "
                                        "verify locally.")
        ok = workspace.artifacts.verify(artifact.content_hash)
        return VerifyResult(
            artifact_id=artifact_id, content_hash=artifact.content_hash, stored=True, ok=ok,
            message="Stored bytes match the recorded SHA-256." if ok else
            "Stored bytes are missing or do not match the recorded SHA-256.")

    @app.get("/api/artifacts/{artifact_id}/lineage", response_model=Lineage)
    def get_lineage(artifact_id: str,
                    direction: Literal["upstream", "downstream"] = "upstream") -> Lineage:
        get_artifact_or_404(artifact_id)
        query = upstream_lineage if direction == "upstream" else downstream_lineage
        return query(workspace, artifact_id)

    @app.exception_handler(ValidationError)
    async def pydantic_error(_: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": exc.errors(include_url=False)})

    if (STATIC_DIR / "index.html").exists():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="studio")
    else:
        @app.get("/", response_class=PlainTextResponse)
        def studio_missing() -> str:
            return ("NeuroWeave API is running, but the Studio UI has not been built.\n"
                    "Build it with: npm --prefix apps/studio install && "
                    "npm --prefix apps/studio run build\nAPI docs: /api/docs\n")

    return app
