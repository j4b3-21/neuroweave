"""First-run tutorial offer is asked once and never blocks scripts or CI."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from neuroweave.cli import app
from neuroweave.onboarding import (
    NO_ONBOARDING_ENV,
    ONBOARDING_FILE_ENV,
    mark_completed,
    mark_declined,
    mark_prompted,
    should_offer_tutorial,
)

runner = CliRunner()


def test_should_offer_only_once_when_interactive(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(ONBOARDING_FILE_ENV, str(tmp_path / "onboarding.json"))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv(NO_ONBOARDING_ENV, raising=False)
    assert should_offer_tutorial(command="nodes", interactive=True) is True
    mark_prompted()
    assert should_offer_tutorial(command="nodes", interactive=True) is False


def test_never_offers_without_tty_or_under_ci_or_for_tutor(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(ONBOARDING_FILE_ENV, str(tmp_path / "onboarding.json"))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv(NO_ONBOARDING_ENV, raising=False)
    assert should_offer_tutorial(command="nodes", interactive=False) is False
    assert should_offer_tutorial(command="tutor", interactive=True) is False
    monkeypatch.setenv("CI", "true")
    assert should_offer_tutorial(command="nodes", interactive=True) is False
    monkeypatch.delenv("CI")
    monkeypatch.setenv(NO_ONBOARDING_ENV, "1")
    assert should_offer_tutorial(command="nodes", interactive=True) is False


def test_declined_and_completed_block_future_offers(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(ONBOARDING_FILE_ENV, str(tmp_path / "onboarding.json"))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv(NO_ONBOARDING_ENV, raising=False)
    mark_declined()
    assert should_offer_tutorial(command="nodes", interactive=True) is False
    (tmp_path / "onboarding.json").unlink()
    mark_completed()
    assert should_offer_tutorial(command="nodes", interactive=True) is False


def test_cli_invoke_does_not_prompt_without_tty(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(ONBOARDING_FILE_ENV, str(tmp_path / "onboarding.json"))
    monkeypatch.delenv("CI", raising=False)
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "guided tutorial" not in result.output
    assert not (tmp_path / "onboarding.json").exists()
