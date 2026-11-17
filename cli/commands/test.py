"""
nlwa test - Natural language web testing.

Usage:
    nlwa test "Log in" --url https://example.com --expect "#dashboard is visible"
    nlwa test "Search for python" --url https://example.com --expect "count(.result) >= 1"
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent.orchestrator import WebAutomationAgent
from auth.redaction import SecretRedactor
from browser.playwright_agent import BrowserController
from cli.assertions.evaluator import AssertionEvaluator
from cli.assertions.parser import parse_assertion
from models.model_selector import ModelSelector

app = typer.Typer(
    context_settings={"allow_interspersed_args": True},
    help="Run natural language tests",
)
console = Console()


@app.callback(invoke_without_command=True)
def test(
    description: str = typer.Argument(..., help="Natural language test description"),
    url: str = typer.Option(..., "--url", "-u", help="Starting URL for the test"),
    output: Path = typer.Option(
        "./test-results", "--output", "-o", help="Output directory for test results"
    ),
    max_steps: int = typer.Option(
        30, "--max-steps", "-m", help="Maximum number of steps"
    ),
    headless: Optional[bool] = typer.Option(
        None,
        "--headless/--headed",
        "-h/-H",
        help="Override configured browser display mode",
    ),
    fail_fast: bool = typer.Option(
        False, "--fail-fast", help="Stop on first failed expectation"
    ),
    expect: Optional[List[str]] = typer.Option(
        None, "--expect", help="Outcome assertion; repeat for multiple postconditions"
    ),
):
    """
    Run a natural language web test.

    The test description should describe what you want to verify on the page.
    The agent executes actions; --expect assertions verify the final page independently.

    Example:
        nlwa test "Add item to cart" --url https://shop.example.com --expect "count(.cart-item) >= 1"
    """
    asyncio.run(
        _test_async(description, url, output, max_steps, headless, fail_fast, expect)
    )


async def _test_async(
    description: str,
    url: str,
    output: Path,
    max_steps: int,
    headless: Optional[bool],
    fail_fast: bool,
    expect: Optional[List[str]] = None,
):
    """Run actions and evaluate explicit postconditions against the final page."""
    redactor = SecretRedactor()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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
        parsed_expectations = [parse_assertion(item) for item in (expect or [])]
        output.mkdir(parents=True, exist_ok=True)
        console.print(Panel("[bold blue]Natural Language Test[/]", title="Test"))
        model_selector = ModelSelector()
        browser = BrowserController(headless=headless)
        agent = WebAutomationAgent(model_selector=model_selector, browser=browser)
        redactor = agent.redactor
        try:
            await agent.initialize()
            result = await agent.execute_task(
                task_description=description, start_url=url, max_steps=max_steps
            )
            test_result["steps"] = result.get("actions", [])
            test_result["execution_status"] = result["status"]
            evaluator = AssertionEvaluator(browser)
            for parsed in parsed_expectations:
                observed = (await evaluator.evaluate(parsed)).to_dict()
                observed["description"] = parsed.raw
                observed["selector"] = parsed.selector
                test_result["assertions"].append(observed)
                if fail_fast and not observed["passed"]:
                    break
            test_result["evidence"] = list(test_result["assertions"])
            test_result["passed"] = (
                result["status"] == "success"
                and bool(parsed_expectations)
                and len(test_result["assertions"]) == len(parsed_expectations)
                and all(item["passed"] for item in test_result["assertions"])
            )
            if not parsed_expectations:
                test_result["status"] = "unverified"
                test_result["error"] = (
                    "No outcome assertions supplied; add one or more --expect options."
                )
            else:
                test_result["status"] = "passed" if test_result["passed"] else "failed"
        finally:
            artifacts = await agent.close()
        test_result["artifacts"] = {
            key: artifacts[key]
            for key in ("videos", "transcript", "screenshots")
            if key in artifacts
        }
        test_result = agent.redactor.redact(test_result)
        report_path = output / f"test-report_{timestamp}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(test_result, f, indent=2, default=str)
        _write_test_report(output / f"test-report_{timestamp}.md", test_result)
        _print_test_results(test_result)
        if test_result["status"] == "unverified":
            console.print("TEST UNVERIFIED: add --expect to verify the final page.")
        else:
            console.print("TEST PASSED" if test_result["passed"] else "TEST FAILED")
        exit_code = 0 if test_result["passed"] else 1
    except Exception as e:
        console.print(f"[bold red]Test Error:[/] {redactor.redact(str(e))}")
        exit_code = 1
    raise typer.Exit(exit_code)


def _write_test_report(path: Path, test_result: dict):
    """Write a markdown test report."""
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Test Report\n\n")
        f.write(f"**Description:** {test_result['description']}\n\n")
        f.write(f"**URL:** {test_result['url']}\n\n")
        f.write(f"**Timestamp:** {test_result['timestamp']}\n\n")

        status = test_result["status"].upper()
        _status_color = "green" if test_result.get("passed") else "red"  # noqa: F841
        f.write(f"**Result:** {status}\n\n")

        f.write("## Assertions\n\n")
        for assertion in test_result.get("assertions", []):
            passed = assertion.get("passed", False)
            emoji = "✓" if passed else "✗"
            f.write(f"- [{emoji}] {assertion.get('description', 'Unknown')}\n")
            if assertion.get("actual_value") is not None:
                f.write(f"  - Actual: {assertion['actual_value']}\n")

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
