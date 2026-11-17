"""
nlwa run - Execute web automation task.

Usage:
    nlwa run --url https://example.com --task "Click the login button"
    nlwa run --url https://example.com --task "Search for 'python'" --output ./output
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from agent.orchestrator import WebAutomationAgent
from auth.redaction import SecretRedactor
from browser.playwright_agent import BrowserController
from models.model_selector import ModelSelector

app = typer.Typer(
    context_settings={"allow_interspersed_args": True},
    help="Execute web automation task",
)
console = Console()


@app.callback(invoke_without_command=True)
def run(
    url: str = typer.Option(..., "--url", "-u", help="Starting URL for the task"),
    task: str = typer.Option(
        ..., "--task", "-t", help="Task description in natural language"
    ),
    output: Path = typer.Option(
        "./output", "--output", "-o", help="Output directory for artifacts"
    ),
    max_steps: int = typer.Option(
        20, "--max-steps", "-m", help="Maximum number of steps"
    ),
    headless: Optional[bool] = typer.Option(
        None,
        "--headless/--headed",
        "-h/-H",
        help="Override configured browser display mode",
    ),
    record_video: Optional[bool] = typer.Option(
        None, "--video/--no-video", help="Override configured video recording"
    ),
    verbose: bool = typer.Option(True, "--verbose/-q", help="Verbose output"),
):
    """
    Execute a web automation task using natural language instructions.

    Example:
        nlwa run --url https://example.com --task "Click the login button"
    """
    asyncio.run(
        _run_async(url, task, output, max_steps, headless, record_video, verbose)
    )


async def _run_async(
    url: str,
    task: str,
    output: Path,
    max_steps: int,
    headless: Optional[bool],
    record_video: Optional[bool],
    verbose: bool,
):
    """Execute a task, finalize artifacts, then persist the completed result."""
    redactor = SecretRedactor()
    try:
        output.mkdir(parents=True, exist_ok=True)
        console.print("[bold blue]Starting task[/]")
        model_selector = ModelSelector()
        browser = BrowserController(headless=headless, record_video=record_video)
        agent = WebAutomationAgent(model_selector=model_selector, browser=browser)
        redactor = agent.redactor
        try:
            await agent.initialize()
            result = await agent.execute_task(
                task_description=task, start_url=url, max_steps=max_steps
            )
        finally:
            artifacts = await agent.close()
        result.update(artifacts)
        result = redactor.redact(result)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        transcript_path = output / f"transcript_{timestamp}.json"
        with open(transcript_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)
        _write_summary(
            output / f"summary_{timestamp}.md",
            result,
            redactor.redact(task),
            redactor.redact(url),
        )
        _print_results(result, verbose)
        if verbose and result.get("videos"):
            console.print(f"\n[dim]Video saved to: {result['videos'][0]}[/]")
        exit_code = 0 if result["status"] == "success" else 1
        console.print(
            "\nTask completed successfully!"
            if exit_code == 0
            else f"\nTask failed: {result['status']}"
        )
    except Exception as e:
        console.print(f"[bold red]Error:[/] {redactor.redact(str(e))}")
        exit_code = 1
    raise typer.Exit(exit_code)


def _write_summary(path: Path, result: dict, task: str, url: str):
    """Write a markdown summary of the task execution."""
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Web Automation Summary\n\n")
        f.write(f"**Task:** {task}\n\n")
        f.write(f"**URL:** {url}\n\n")
        f.write(f"**Status:** {result['status']}\n\n")
        f.write(f"**Steps Taken:** {result['steps_taken']}\n\n")

        if result.get("actions"):
            f.write("## Actions\n\n")
            for i, action in enumerate(result["actions"], 1):
                status = action.get("status", "unknown")
                status_emoji = "✓" if status == "success" else "✗"
                f.write(
                    f"{i}. [{status_emoji}] `{action.get('action', 'unknown')}` - {status}\n"
                )

        if result.get("extractions"):
            f.write("\n## Extractions\n\n")
            for ext in result["extractions"]:
                f.write(f"- `{ext['selector']}` ({ext['attr']}): {ext['value']}\n")

        if result.get("errors"):
            f.write("\n## Errors\n\n")
            for error in result["errors"]:
                f.write(f"- {error}\n")


def _print_results(result: dict, verbose: bool):
    """Print results to console."""
    # Status table
    table = Table(title="Task Results")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Status", result["status"])
    table.add_row("Steps", str(result["steps_taken"]))
    table.add_row("Actions", str(len(result.get("actions", []))))
    table.add_row("Extractions", str(len(result.get("extractions", []))))

    if result.get("errors"):
        table.add_row("Errors", str(len(result["errors"])))

    console.print(table)

    if verbose and result.get("actions"):
        console.print("\n[bold]Action Details:[/]")
        for action in result["actions"]:
            status_color = "green" if action.get("status") == "success" else "red"
            console.print(
                f"  [{status_color}]{action.get('action', 'unknown')}[/] - {action.get('status', 'unknown')}"
            )


if __name__ == "__main__":
    app()
