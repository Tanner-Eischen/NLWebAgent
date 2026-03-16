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

import typer
from rich.console import Console
from rich.table import Table

from agent.orchestrator import WebAutomationAgent
from models.model_selector import ModelSelector
from browser.playwright_agent import BrowserController

app = typer.Typer(help="Execute web automation task")
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
    headless: bool = typer.Option(
        False, "--headless", "-h", help="Run browser in headless mode"
    ),
    record_video: bool = typer.Option(
        True, "--video/--no-video", help="Record video of session"
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
    headless: bool,
    record_video: bool,
    verbose: bool,
):
    """Async implementation of run command."""
    import os

    # Override config via environment variables
    os.environ["HEADLESS"] = str(headless).lower()
    os.environ["RECORD_VIDEO"] = str(record_video).lower()

    # Create output directory
    output.mkdir(parents=True, exist_ok=True)

    # Initialize components
    console.print(f"[bold blue]Starting task:[/] {task}")
    console.print(f"[dim]URL: {url}[/dim]")

    model_selector = ModelSelector()
    browser = BrowserController()
    agent = WebAutomationAgent(
        model_selector=model_selector,
        browser=browser,
    )

    try:
        await agent.initialize()

        result = await agent.execute_task(
            task_description=task,
            start_url=url,
            max_steps=max_steps,
        )

        # Save results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Save transcript
        transcript_path = output / f"transcript_{timestamp}.json"
        with open(transcript_path, "w") as f:
            json.dump(result, f, indent=2, default=str)

        # Save summary
        summary_path = output / f"summary_{timestamp}.md"
        _write_summary(summary_path, result, task, url)

        # Print results
        _print_results(result, verbose)

        # Return appropriate exit code
        if result["status"] == "success":
            console.print("\n[bold green]Task completed successfully![/]")
            raise typer.Exit(0)
        else:
            console.print(f"\n[bold red]Task failed: {result['status']}[/]")
            raise typer.Exit(1)

    except Exception as e:
        console.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(1)
    finally:
        artifacts = await agent.close()
        if verbose and artifacts.get("videos"):
            console.print(f"\n[dim]Video saved to: {artifacts['videos'][0]}[/]")


def _write_summary(path: Path, result: dict, task: str, url: str):
    """Write a markdown summary of the task execution."""
    with open(path, "w") as f:
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
