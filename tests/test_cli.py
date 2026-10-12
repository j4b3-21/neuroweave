from __future__ import annotations

import re

from typer.testing import CliRunner

from neuroweave.cli import app

runner = CliRunner()


def nw(project, *args):
    return runner.invoke(app, ["--project", str(project.root), *args])


def test_cli_research_workflow(demo_project) -> None:
    result = nw(demo_project, "nodes")
    assert result.exit_code == 0, result.output
    assert "demo_nodes:load_dataset" in result.output

    result = nw(demo_project, "workflows", "list")
    assert "rainfall-yield" in result.output

    result = nw(demo_project, "validate", "rainfall-yield")
    assert result.exit_code == 0, result.output
    assert "load -> validate -> transform" in result.output

    result = nw(demo_project, "run", "rainfall-yield")
    assert result.exit_code == 0, result.output
    run_id = re.search(r"Run (run_\S+): SUCCEEDED", result.output).group(1)

    result = nw(demo_project, "run", "rainfall-yield")
    assert "7 node(s) reused from cache" in result.output
    second_id = re.search(r"Run (run_\S+):", result.output).group(1)

    result = nw(demo_project, "show", run_id)
    assert result.exit_code == 0 and "pearson_r" in result.output

    result = nw(demo_project, "logs", run_id, "load")
    assert "Loaded 24 rows" in result.output

    result = nw(demo_project, "runs")
    assert run_id in result.output and second_id in result.output

    result = nw(demo_project, "artifacts", "--run", run_id)
    report_id = re.search(r"(art_\w+)\s+report\s+output", result.output).group(1)

    result = nw(demo_project, "lineage", report_id)
    assert "data/field_trial.csv" in result.output and "--used-->" in result.output

    result = nw(demo_project, "verify", "--all")
    assert result.exit_code == 0 and "0 corrupt" in result.output

    result = nw(demo_project, "compare", run_id, second_id)
    assert "same workflow snapshot" in result.output

    result = nw(demo_project, "reproduce", run_id)
    assert result.exit_code == 0, result.output
    assert "Verdict: reproduced" in result.output


def test_cli_errors_are_actionable(demo_project, tmp_path) -> None:
    assert "nw init" in runner.invoke(app, ["--project", str(tmp_path), "runs"]).output
    result = nw(demo_project, "run", "missing")
    assert result.exit_code == 1 and "does not exist" in result.output
    result = nw(demo_project, "show", "run_x")
    assert result.exit_code == 1 and "nw runs" in result.output


def test_cli_refuses_invalid_workflow(demo_project) -> None:
    workflow = demo_project.load_workflow("rainfall-yield")
    workflow.nodes[0].params["path"] = 42
    demo_project.save_workflow(workflow)
    result = nw(demo_project, "run", "rainfall-yield")
    assert result.exit_code == 1
    assert "invalid_param" in result.output and "nothing was executed" in result.output
    assert demo_project.db.list_runs() == []


def test_workflow_import_export(demo_project, tmp_path) -> None:
    exported = tmp_path / "out.json"
    assert nw(demo_project, "workflows", "export", "rainfall-yield", "-o",
              str(exported)).exit_code == 0
    result = nw(demo_project, "workflows", "import", str(exported))
    assert result.exit_code == 1 and "--force" in result.output
    assert nw(demo_project, "workflows", "import", str(exported), "--force").exit_code == 0


def test_cli_env_show_and_export(demo_project, tmp_path) -> None:
    result = nw(demo_project, "run", "rainfall-yield")
    assert result.exit_code == 0, result.output
    run_id = re.search(r"Run (run_\S+): SUCCEEDED", result.output).group(1)

    result = nw(demo_project, "env", "show", run_id)
    assert result.exit_code == 0, result.output
    assert "Lock hash:" in result.output
    assert "NeuroWeave:" in result.output
    assert ("typer==" in result.output or "pydantic==" in result.output
            or "fastapi==" in result.output)

    out = tmp_path / "requirements.lock"
    result = nw(demo_project, "env", "export", run_id, "-o", str(out))
    assert result.exit_code == 0, result.output
    assert out.is_file() and "Wrote" in result.output
    assert out.read_text(encoding="utf-8")


def test_cli_reproduce_rebuild_requires_isolated(demo_project) -> None:
    result = nw(demo_project, "run", "rainfall-yield")
    run_id = re.search(r"Run (run_\S+): SUCCEEDED", result.output).group(1)
    result = nw(demo_project, "reproduce", run_id, "--rebuild")
    assert result.exit_code == 1
    assert "--isolated" in result.output
