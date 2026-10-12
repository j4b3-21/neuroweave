"""End-to-end isolated reproduction that rebuilds an environment with uv.

Skipped unless ``NEUROWEAVE_NETWORK_TESTS=1`` and ``uv`` is on PATH. CI keeps the
no-network rule; run this locally when validating the rebuild path:

    NEUROWEAVE_NETWORK_TESTS=1 pytest tests/test_isolated_network.py -q
"""

from __future__ import annotations

import os
import shutil

import pytest

from neuroweave.runtime.executor import run_workflow
from neuroweave.runtime.isolated import IsolatedReproductionError, find_uv, reproduce_isolated

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("NEUROWEAVE_NETWORK_TESTS") != "1",
        reason="Set NEUROWEAVE_NETWORK_TESTS=1 to run isolated rebuilds (needs network).",
    ),
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH."),
]


def test_isolated_reproduction_of_demo_matches_lock(demo_project, demo_registry):
    find_uv()
    original = run_workflow(
        demo_project, demo_project.load_workflow("rainfall-yield"), demo_registry, seed=7)
    assert original.status == "SUCCEEDED", original.error
    assert original.environment and original.environment.get("lock")

    try:
        report, env_dir = reproduce_isolated(demo_project, original.id, log=print)
    except IsolatedReproductionError as exc:
        pytest.fail(f"isolated reproduction failed: {exc}")

    assert (env_dir / ".complete").is_file()
    assert report.verdict == "reproduced", report
    assert report.environment_match == "identical", report
    assert report.isolated is True
    assert all(c.identical for c in report.outputs)
