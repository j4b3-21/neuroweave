from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from neuroweave.server.app import create_app

HEADERS = {"X-NeuroWeave-Client": "test"}


@pytest.fixture
def client(demo_project):
    with TestClient(create_app(demo_project.root)) as test_client:
        yield test_client


def wait_for(client, run_id, timeout=60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()["run"]
        if run["status"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            return run
        time.sleep(0.2)
    raise AssertionError(f"run {run_id} did not finish")


def test_security_checks(client) -> None:
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 403
    response = client.post("/api/workflows", json={"id": "x", "name": "x"})
    assert response.status_code == 403
    assert client.post("/api/workflows", json={"id": "x", "name": "x"},
                       headers=HEADERS).status_code == 201


def test_catalog_and_workflow_editing(client) -> None:
    catalog = client.get("/api/nodes").json()
    ids = {d["id"] for d in catalog["definitions"]}
    assert "demo_nodes:write_report" in ids and catalog["errors"] == []

    workflow = client.get("/api/workflows/rainfall-yield").json()
    workflow["nodes"][0]["position"] = {"x": 10, "y": 20}
    saved = client.put("/api/workflows/rainfall-yield", json=workflow, headers=HEADERS).json()
    assert saved["validation"]["valid"]
    assert client.get("/api/workflows/rainfall-yield").json()["nodes"][0]["position"] == \
        {"x": 10.0, "y": 20.0}

    workflow["edges"].append({"source": "statistics", "source_port": "output",
                              "target": "load", "target_port": "path"})
    report = client.post("/api/workflows/rainfall-yield/validate", json=workflow,
                         headers=HEADERS).json()
    assert not report["valid"]
    assert {"param_and_connection", "cycle"} <= {i["code"] for i in report["issues"]}

    assert client.get("/api/workflows/nope").status_code == 404
    bad = client.put("/api/workflows/rainfall-yield", json={"id": "other", "name": "x"},
                     headers=HEADERS)
    assert bad.status_code == 400


def test_run_lifecycle_through_worker_process(client) -> None:
    response = client.post("/api/workflows/rainfall-yield/runs", json={}, headers=HEADERS)
    assert response.status_code == 202
    run = wait_for(client, response.json()["id"])
    assert run["status"] == "SUCCEEDED", run["error"]
    assert run["trigger"] == "studio" and run["environment"]["python"]["version"]

    detail = client.get(f"/api/runs/{run['id']}").json()
    assert [n["execution"]["status"] for n in detail["nodes"]] == ["SUCCEEDED"] * 7
    report_node = next(n for n in detail["nodes"] if n["execution"]["node_id"] == "report")
    artifact_id = report_node["outputs"][0]["id"]
    assert "rainfall" in detail["workflow"]["name"].lower()

    logs = client.get(f"/api/runs/{run['id']}/logs/load").text
    assert "Loaded 24 rows" in logs

    artifact = client.get(f"/api/artifacts/{artifact_id}").json()
    assert artifact["previewable"] and artifact["artifact"]["media_type"] == "text/markdown"
    content = client.get(f"/api/artifacts/{artifact_id}/content")
    assert content.text.startswith("# Rainfall and crop yield")
    assert content.headers["x-content-sha256"] == artifact["artifact"]["content_hash"]
    assert client.post(f"/api/artifacts/{artifact_id}/verify", headers=HEADERS).json()["ok"]

    lineage = client.get(f"/api/artifacts/{artifact_id}/lineage").json()
    assert any(n["label"] == "data/field_trial.csv" for n in lineage["nodes"])

    reproduction = client.post(f"/api/runs/{run['id']}/reproduce", headers=HEADERS).json()
    wait_for(client, reproduction["id"])
    report = client.get(f"/api/runs/{reproduction['id']}/reproduction").json()
    assert report["verdict"] == "reproduced"

    comparison = client.get("/api/compare", params={"a": run["id"],
                                                    "b": reproduction["id"]}).json()
    assert comparison["same_snapshot"]


def test_invalid_workflow_is_not_started(client) -> None:
    workflow = client.get("/api/workflows/rainfall-yield").json()
    workflow["nodes"][0]["params"] = {}
    client.put("/api/workflows/rainfall-yield", json=workflow, headers=HEADERS)
    response = client.post("/api/workflows/rainfall-yield/runs", json={}, headers=HEADERS)
    assert response.status_code == 422
    assert response.json()["detail"]["validation"]["issues"][0]["code"] == "missing_input"
    assert client.get("/api/runs").json() == []


def test_corrupted_artifact_is_reported(client, demo_project) -> None:
    run_id = client.post("/api/workflows/rainfall-yield/runs", json={},
                         headers=HEADERS).json()["id"]
    wait_for(client, run_id)
    artifact = client.get("/api/artifacts", params={"run_id": run_id, "role": "output"}).json()[0]
    demo_project.artifacts.path_for(artifact["content_hash"]).write_bytes(b"x")
    assert client.get(f"/api/artifacts/{artifact['id']}/content").status_code == 409
    assert not client.post(f"/api/artifacts/{artifact['id']}/verify", headers=HEADERS).json()["ok"]
