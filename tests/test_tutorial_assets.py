"""The packaged tutorial sample must stay identical to examples/research_demo."""

from __future__ import annotations

from pathlib import Path

from neuroweave.tutorial import ASSET_FILES, asset_bytes, assets_root

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "research_demo"


def test_packaged_assets_match_research_demo_byte_for_byte():
    assert assets_root().is_dir()
    for relative in ASSET_FILES:
        packaged = asset_bytes(relative)
        example = (DEMO / relative).read_bytes()
        assert packaged == example, f"{relative} drifted from examples/research_demo/"


def test_project_config_accepts_tutorial_flag(tmp_path):
    from neuroweave.store.workspace import Workspace

    ws = Workspace.init(tmp_path / "proj", name="Tutorial", node_modules=["demo_nodes"])
    config = ws.config
    config.tutorial = True
    ws.save_config(config)
    assert Workspace(ws.root).config.tutorial is True
