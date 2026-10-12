"""Trust boundaries of opening a project: what may run code, and when."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from neuroweave.server.app import create_app
from neuroweave.store.workspace import Workspace

HEADERS = {"X-NeuroWeave-Client": "test"}


def wait_for(client: TestClient, run_id: str, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()["run"]
        if run["status"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            return run
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} did not finish")


def marker_module(path: Path, marker: Path, *, fail: bool = False) -> None:
    """A Python file whose only effect on import is to create ``marker``."""
    path.write_text(f"import pathlib\npathlib.Path({str(marker)!r}).write_text('imported')\n"
                    + ("raise SystemExit(3)\n" if fail else ""), encoding="utf-8")


def test_project_files_named_like_stdlib_modules_are_not_imported(tmp_path) -> None:
    project = tmp_path / "project"
    Workspace.init(project)
    marker = tmp_path / "shadowed"
    marker_module(project / "argparse.py", marker, fail=True)

    with TestClient(create_app(project, allowed_hosts_extra=["testserver"])) as client:
        catalog = client.get("/api/nodes").json()
        assert catalog["errors"] == [] and catalog["definitions"] == []
        client.post("/api/workflows", json={"id": "empty", "name": "Empty"}, headers=HEADERS)
        run = client.post("/api/workflows/empty/runs", json={}, headers=HEADERS).json()
        assert wait_for(client, run["id"])["status"] == "SUCCEEDED"
    assert not marker.exists()


def test_cross_site_browser_requests_cannot_reach_the_api(tmp_path) -> None:
    project = tmp_path / "project"
    Workspace.init(project, node_modules=["planted"])
    marker = tmp_path / "imported"
    marker_module(project / "planted.py", marker)

    with TestClient(create_app(project, allowed_hosts_extra=["testserver"])) as client:
        for site in ("cross-site", "same-site"):
            response = client.get("/api/nodes", headers={"Sec-Fetch-Site": site})
            assert response.status_code == 403, site
            assert client.post("/api/workflows", json={"id": "x", "name": "x"},
                               headers={**HEADERS, "Sec-Fetch-Site": site}).status_code == 403
        assert not marker.exists()

        assert client.get("/api/health", headers={"Sec-Fetch-Site": "same-origin"}).status_code \
            == 200
        assert client.get("/api/health", headers={"Sec-Fetch-Site": "none"}).status_code == 200
        assert client.get("/api/health").status_code == 200
        assert client.get("/", headers={"Sec-Fetch-Site": "cross-site"}).status_code != 403
