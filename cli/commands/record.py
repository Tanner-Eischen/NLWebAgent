"""
nlwa record - Record browser session and generate Playwright test code.

Usage:
    nlwa record --url https://example.com --output test.spec.ts
    nlwa record --url https://example.com --task "Complete checkout" --output checkout.spec.ts
"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from agent.orchestrator import WebAutomationAgent
from models.model_selector import ModelSelector
from browser.playwright_agent import BrowserController
from cli.codegen.generator import generate_playwright_test

app = typer.Typer(help="Record session and generate Playwright test code")
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
    headless: bool = typer.Option(
        False, "--headless/-H", help="Run browser in headless mode"
    ),
    add_assertions: bool = typer.Option(
        True, "--assertions/--no-assertions", help="Add assertion suggestions"
    ),
):
    """
    Record a browser session and generate Playwright test code.

    The agent will execute the specified task (or you can interact manually)
    and the actions will be recorded and converted to Playwright test code.

    Example:
        nlwa record --url https://example.com --task "Search for 'test'" --output search.spec.ts
    """
    asyncio.run(
        _record_async(url, task, output, test_name, max_steps, headless, add_assertions)
    )


async def _record_async(
    url: str,
    task: Optional[str],
    output: Path,
    test_name: Optional[str],
    max_steps: int,
    headless: bool,
    add_assertions: bool,
):
    """Async implementation of record command."""
    import os

    os.environ["HEADLESS"] = str(headless).lower()
    os.environ["RECORD_VIDEO"] = "true"

    console.print(Panel("[bold blue]Recording Session[/]", title="NLWebAgent"))
    console.print(f"[dim]URL: {url}[/dim]")
    console.print(f"[dim]Output: {output}[/dim]\n")

    model_selector = ModelSelector()
    browser = BrowserController()
    agent = WebAutomationAgent(
        model_selector=model_selector,
        browser=browser,
    )

    recording = {
        "url": url,
        "task": task,
        "start_time": datetime.now().isoformat(),
        "actions": [],
        "extractions": [],
        "screenshots": [],
    }

    try:
        await agent.initialize()

        if task:
            # Execute task and record actions
            result = await agent.execute_task(
                task_description=task,
                start_url=url,
                max_steps=max_steps,
            )
            recording["actions"] = result.get("actions", [])
            recording["extractions"] = result.get("extractions", [])
            recording["status"] = result.get("status")
        else:
            # Manual recording mode - just navigate and wait for user
            await browser.navigate(url)
            console.print(
                "[yellow]Manual recording mode - press Ctrl+C to stop recording[/]"
            )
            # Record initial page state
            recording["actions"].append(
                {
                    "action": f"NAVIGATE:{url}",
                    "status": "success",
                }
            )
            # Wait for user to finish
            try:
                await asyncio.sleep(300)  # 5 minute timeout
            except KeyboardInterrupt:
                console.print("\n[yellow]Recording stopped by user[/]")

        recording["end_time"] = datetime.now().isoformat()

        # Get the transcript from the browser
        transcript = browser.transcript
        recording["transcript"] = transcript

        # Generate Playwright test code
        test_name_final = test_name or _generate_test_name(task, url)
        playwright_code = generate_playwright_test(
            recording=recording,
            test_name=test_name_final,
            add_assertions=add_assertions,
        )

        # Ensure output directory exists
        output.parent.mkdir(parents=True, exist_ok=True)

        # Write the generated test
        with open(output, "w") as f:
            f.write(playwright_code)

        console.print(f"\n[bold green]Generated Playwright test:[/] {output}")

        # Also save the recording JSON for reference
        recording_path = output.with_suffix(".recording.json")
        with open(recording_path, "w") as f:
            json.dump(recording, f, indent=2, default=str)
        console.print(f"[dim]Recording saved to: {recording_path}[/]")

        # Print summary
        _print_recording_summary(recording)

        raise typer.Exit(0)

    except KeyboardInterrupt:
        console.print("\n[yellow]Recording interrupted[/]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(1)
    finally:
        await agent.close()


def _generate_test_name(task: Optional[str], url: str) -> str:
    """Generate a test name from task or URL."""
    if task:
        # Clean up task for test name
        name = task.lower()
        name = "".join(c if c.isalnum() or c == " " else "" for c in name)
        name = name.replace(" ", "_")[:50]
        return f"test_{name}" if name else "test_recorded"
    else:
        # Use URL domain
        from urllib.parse import urlparse

        domain = urlparse(url).netloc.replace(".", "_")
        return f"test_{domain}"


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
