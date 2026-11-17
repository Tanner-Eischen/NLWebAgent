"""
nlwa record - Record browser session and generate Playwright test code.

Usage:
    nlwa record --url https://example.com --task "Click the login button" --output test.spec.ts
    nlwa record --url https://example.com --task "Complete checkout" --output checkout.spec.ts
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent.orchestrator import WebAutomationAgent
from auth.redaction import SecretRedactor
from browser.playwright_agent import BrowserController
from cli.codegen.generator import generate_playwright_test
from models.model_selector import ModelSelector

app = typer.Typer(
    context_settings={"allow_interspersed_args": True},
    help="Record session and generate Playwright test code",
)
console = Console()


@app.callback(invoke_without_command=True)
def record(
    url: str = typer.Option(..., "--url", "-u", help="Starting URL for recording"),
    task: Optional[str] = typer.Option(
        None, "--task", "-t", help="Task to execute during recording"
    ),
    output: Path = typer.Option(
        ..., "--output", "-o", help="Output file for generated Playwright test"
    ),
    test_name: Optional[str] = typer.Option(
        None, "--name", "-n", help="Name for the generated test"
    ),
    max_steps: int = typer.Option(
        30, "--max-steps", "-m", help="Maximum number of steps to record"
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
    add_assertions: bool = typer.Option(
        True, "--assertions/--no-assertions", help="Add assertion suggestions"
    ),
):
    """
    Record a browser session and generate Playwright test code.

    The agent executes the required task and exports the executed actions.
    Manual interaction recording is not supported.

    Example:
        nlwa record --url https://example.com --task "Search for 'test'" --output search.spec.ts
    """
    asyncio.run(
        _record_async(
            url,
            task,
            output,
            test_name,
            max_steps,
            headless,
            add_assertions,
            record_video,
        )
    )


async def _record_async(
    url: str,
    task: Optional[str],
    output: Path,
    test_name: Optional[str],
    max_steps: int,
    headless: Optional[bool],
    add_assertions: bool,
    record_video: Optional[bool] = None,
):
    """Export an automated session; manual interaction capture is unsupported."""
    redactor = SecretRedactor()
    if not task or not task.strip():
        console.print(
            "Recording requires --task. Manual interaction capture is not supported."
        )
        raise typer.Exit(2)
    try:
        console.print(Panel("[bold blue]Recording Session[/]", title="NLWebAgent"))
        model_selector = ModelSelector()
        browser = BrowserController(headless=headless, record_video=record_video)
        agent = WebAutomationAgent(model_selector=model_selector, browser=browser)
        redactor = agent.redactor
        started = datetime.now().isoformat()
        try:
            await agent.initialize()
            result = await agent.execute_task(
                task_description=task, start_url=url, max_steps=max_steps
            )
        finally:
            artifacts = await agent.close()
        recording = {
            "url": url,
            "task": task,
            "start_time": started,
            "end_time": datetime.now().isoformat(),
            "actions": result.get("actions", []),
            "extractions": result.get("extractions", []),
            "screenshots": result.get("screenshots", []),
            "status": result["status"],
            "transcript": browser.transcript,
            "artifacts": {
                key: artifacts[key]
                for key in ("videos", "transcript", "screenshots")
                if key in artifacts
            },
        }
        recording = agent.redactor.redact(recording)
        test_name_final = agent.redactor.redact(test_name or "test_recorded")
        playwright_code = generate_playwright_test(
            recording=recording,
            test_name=test_name_final,
            add_assertions=add_assertions,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(playwright_code, encoding="utf-8")
        recording_path = output.with_suffix(".recording.json")
        recording_path.write_text(
            json.dumps(recording, indent=2, default=str), encoding="utf-8"
        )
        console.print(f"\n[bold green]Generated Playwright test:[/] {output}")
        _print_recording_summary(recording)
        exit_code = 0 if result["status"] == "success" else 1
    except KeyboardInterrupt:
        console.print("Recording interrupted")
        exit_code = 1
    except Exception as e:
        console.print(f"[bold red]Error:[/] {redactor.redact(str(e))}")
        exit_code = 1
    raise typer.Exit(exit_code)


def _print_recording_summary(recording: dict):
    """Print a summary of the recording."""
    table = Table(title="Recording Summary")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("URL", recording.get("url", "N/A"))
    table.add_row(
        "Task", recording.get("task", "Manual recording") or "Manual recording"
    )
    table.add_row("Actions Recorded", str(len(recording.get("actions", []))))
    table.add_row("Extractions", str(len(recording.get("extractions", []))))

    console.print(table)

    # Print actions
    if recording.get("actions"):
        console.print("\n[bold]Recorded Actions:[/]")
        for i, action in enumerate(recording["actions"], 1):
            console.print(f"  {i}. {action.get('action', 'unknown')}")


if __name__ == "__main__":
    app()
