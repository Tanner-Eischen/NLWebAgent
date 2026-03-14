"""
NLWebAgent CLI - Natural Language Web Testing Agent.

A CLI tool for web automation using natural language instructions.
Powered by Playwright with AI-guided actions.
"""
import typer
from typing import Optional

app = typer.Typer(
    name="nlwa",
    help="NLWebAgent - Natural Language Web Testing Agent",
    add_completion=False,
)


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-v", help="Show version and exit"
    ),
):
    """NLWebAgent - Natural Language Web Testing Agent."""
    if version:
        typer.echo("nlwa version 0.1.0")
        raise typer.Exit()


# Import and register commands
from cli.commands import run, test as test_cmd, assert_cmd, record

app.add_typer(run.app, name="run")
app.add_typer(test_cmd.app, name="test")
app.add_typer(assert_cmd.app, name="assert")
app.add_typer(record.app, name="record")


if __name__ == "__main__":
    app()
