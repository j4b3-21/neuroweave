from __future__ import annotations

from pathlib import Path

import typer

from src.cli.workspace import initialize_workspace


app = typer.Typer(
    add_completion=False,
    help="NeuroWeave command line interface.",
)


@app.callback()
def cli() -> None:
    """NeuroWeave command line interface."""


@app.command()
def init() -> None:
    """Initialize the local NeuroWeave workspace."""

    result = initialize_workspace(Path.cwd())

    for line in result.summary_lines():
        typer.echo(line)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
