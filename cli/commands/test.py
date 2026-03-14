"""
nlwa test - Natural language web testing.

Usage:
    nlwa test "Verify user can login" --url https://example.com
    nlwa test "Check search returns results" --url https://example.com --output ./test-results
"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from agent.orchestrator import WebAutomationAgent
from models.model_selector import ModelSelector
from browser.playwright_agent import BrowserController

app = typer.Typer(help="Run natural language tests")
console = Console()


@app.callback(invoke_without_command=True)
def test(
    description: str = typer.Argument(..., help="Natural language test description"),
    url: str = typer.Option(..., "--url", "-u", help="Starting URL for the test"),
    output: Path = typer.Option("./test-results", "--output", "-o", help="Output directory for test results"),
    max_steps: int = typer.Option(30, "--max-steps", "-m", help="Maximum number of steps"),
    headless: bool = typer.Option(False, "--headless", "-h", help="Run browser in headless mode"),
    fail_fast: bool = typer.Option(False, "--fail-fast", help="Stop on first failure"),
):
    """
    Run a natural language web test.

    The test description should describe what you want to verify on the page.
    The agent will execute actions and verify outcomes semantically.

    Example:
        nlwa test "Verify user can add item to cart" --url https://shop.example.com
    """
    asyncio.run(_test_async(description, url, output, max_steps, headless, fail_fast))


async def _test_async(
    description: str,
    url: str,
    output: Path,
    max_steps: int,
    headless: bool,
    fail_fast: bool,
):
    """Async implementation of test command."""
    import os

    # Override config via environment variables
    os.environ["HEADLESS"] = str(headless).lower()

    # Create output directory
    output.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    console.print(Panel(f"[bold blue]Natural Language Test[/]\n{description}", title="Test"))
    console.print(f"[dim]URL: {url}[/dim]\n")

    model_selector = ModelSelector()
    browser = BrowserController()
    agent = WebAutomationAgent(
        model_selector=model_selector,
        browser=browser,
    )

    test_result = {
        "description": description,
        "url": url,
        "timestamp": timestamp,
        "status": "running",
        "steps": [],
        "assertions": [],
        "evidence": [],
        "passed": False,
    }

    try:
        await agent.initialize()

        # Execute the test
        result = await agent.execute_task(
            task_description=f"Test: {description}",
            start_url=url,
            max_steps=max_steps,
        )

        # Analyze results for test verification
        test_result["steps"] = result.get("actions", [])
        test_result["status"] = result["status"]

        # Generate assertions based on test description and actions
        assertions = _generate_assertions(description, result)
        test_result["assertions"] = assertions

        # Determine pass/fail
        passed = (
            result["status"] == "success"
            and all(a.get("passed", False) for a in assertions)
        )
        test_result["passed"] = passed

        # Save test report
        report_path = output / f"test-report_{timestamp}.json"
        with open(report_path, "w") as f:
            json.dump(test_result, f, indent=2, default=str)

        # Save human-readable report
        md_report_path = output / f"test-report_{timestamp}.md"
        _write_test_report(md_report_path, test_result)

        # Print results
        _print_test_results(test_result)

        # Return appropriate exit code
        if passed:
            console.print(f"\n[bold green]TEST PASSED[/]")
            raise typer.Exit(0)
        else:
            console.print(f"\n[bold red]TEST FAILED[/]")
            raise typer.Exit(1)

    except Exception as e:
        console.print(f"[bold red]Test Error:[/] {e}")
        test_result["status"] = "error"
        test_result["error"] = str(e)
        raise typer.Exit(1)
    finally:
        await agent.close()


def _generate_assertions(description: str, result: dict) -> List[dict]:
    """Generate and evaluate assertions based on test description and results."""
    assertions = []

    # Basic assertion: task completed successfully
    assertions.append({
        "type": "task_completion",
        "description": "Task executed without errors",
        "expected": "success",
        "actual": result["status"],
        "passed": result["status"] == "success",
    })

    # Check for specific keywords in description
    desc_lower = description.lower()

    # Login-related assertions
    if "login" in desc_lower:
        actions = [a.get("action", "").lower() for a in result.get("actions", [])]
        has_username = any("username" in a or "#user" in a for a in actions)
        has_password = any("password" in a or "#pass" in a for a in actions)
        has_submit = any("login" in a or "submit" in a or "click" in a for a in actions)

        assertions.append({
            "type": "action_sequence",
            "description": "Login form filled",
            "passed": has_username and has_password,
        })

    # Search-related assertions
    if "search" in desc_lower:
        extractions = result.get("extractions", [])
        actions = [a.get("action", "") for a in result.get("actions", [])]
        has_type = any("TYPE" in a for a in actions)
        has_search_action = has_type or any("search" in str(e).lower() for e in extractions)

        assertions.append({
            "type": "action_performed",
            "description": "Search action executed",
            "passed": has_search_action,
        })

    # Extraction assertions
    for extraction in result.get("extractions", []):
        assertions.append({
            "type": "extraction",
            "description": f"Extracted {extraction['attr']} from {extraction['selector']}",
            "actual": extraction["value"],
            "passed": extraction["value"] is not None,
        })

    return assertions


def _write_test_report(path: Path, test_result: dict):
    """Write a markdown test report."""
    with open(path, "w") as f:
        f.write("# Test Report\n\n")
        f.write(f"**Description:** {test_result['description']}\n\n")
        f.write(f"**URL:** {test_result['url']}\n\n")
        f.write(f"**Timestamp:** {test_result['timestamp']}\n\n")

        status = "PASSED" if test_result.get("passed") else "FAILED"
        status_color = "green" if test_result.get("passed") else "red"
        f.write(f"**Result:** {status}\n\n")

        f.write("## Assertions\n\n")
        for assertion in test_result.get("assertions", []):
            passed = assertion.get("passed", False)
            emoji = "✓" if passed else "✗"
            f.write(f"- [{emoji}] {assertion.get('description', 'Unknown')}\n")
            if assertion.get("actual"):
                f.write(f"  - Actual: {assertion['actual']}\n")

        f.write("\n## Steps Executed\n\n")
        for i, step in enumerate(test_result.get("steps", []), 1):
            status = step.get("status", "unknown")
            emoji = "✓" if status == "success" else "✗"
            f.write(f"{i}. [{emoji}] `{step.get('action', 'unknown')}`\n")

        if test_result.get("error"):
            f.write(f"\n## Error\n\n```\n{test_result['error']}\n```\n")


def _print_test_results(test_result: dict):
    """Print test results to console."""
    # Summary table
    table = Table(title="Test Results")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    passed = test_result.get("passed", False)
    status_style = "green" if passed else "red"
    table.add_row("Status", f"[{status_style}]{test_result['status']}[/]")
    table.add_row("Result", f"[{status_style}]{'PASSED' if passed else 'FAILED'}[/]")
    table.add_row("Steps", str(len(test_result.get("steps", []))))
    table.add_row("Assertions", str(len(test_result.get("assertions", []))))

    console.print(table)

    # Assertions
    if test_result.get("assertions"):
        console.print("\n[bold]Assertions:[/]")
        for assertion in test_result["assertions"]:
            passed = assertion.get("passed", False)
            color = "green" if passed else "red"
            console.print(
                f"  [{color}]{'✓' if passed else '✗'}[/] {assertion.get('description', 'Unknown')}"
            )


if __name__ == "__main__":
    app()
