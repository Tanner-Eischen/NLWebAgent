"""
nlwa assert - Semantic assertions on web pages.

Usage:
    nlwa assert "price < 50" --url https://shop.example.com/product/123
    nlwa assert "title contains 'Welcome'" --url https://example.com
    nlwa assert "button is visible" --selector "#submit" --url https://example.com
"""
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from browser.playwright_agent import BrowserController
from cli.assertions.parser import parse_assertion
from cli.assertions.evaluator import AssertionEvaluator

app = typer.Typer(help="Run semantic assertions on web pages")
console = Console()


@app.callback(invoke_without_command=True)
def assert_cmd(
    assertion: str = typer.Argument(..., help="Assertion expression (e.g., 'price < 50')"),
    url: str = typer.Option(..., "--url", "-u", help="URL to assert against"),
    selector: Optional[str] = typer.Option(None, "--selector", "-s", help="CSS selector for target element"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file for assertion result"),
    headless: bool = typer.Option(True, "--headless/-H", help="Run browser in headless mode"),
):
    """
    Run a semantic assertion against a web page.

    Supported assertion types:
    - Numeric comparisons: "price < 50", "count >= 5"
    - String matching: "title contains 'Sale'", "url starts with 'https'"
    - Visual checks: "button is visible", "form has no errors"

    Example:
        nlwa assert "price < 50" --url https://shop.example.com/product/123
    """
    asyncio.run(_assert_async(assertion, url, selector, output, headless))


async def _assert_async(
    assertion: str,
    url: str,
    selector: Optional[str],
    output: Optional[Path],
    headless: bool,
):
    """Async implementation of assert command."""
    import os
    os.environ["HEADLESS"] = str(headless).lower()

    browser = BrowserController()

    try:
        await browser.create_session()
        await browser.navigate(url)

        # Parse and evaluate the assertion using the evaluator module
        parsed = parse_assertion(assertion)
        evaluator = AssertionEvaluator(browser)
        result = await evaluator.evaluate(parsed)

        # Convert to dict for output
        result_dict = result.to_dict()
        result_dict["assertion"] = assertion

        # Print result
        _print_assertion_result(assertion, result_dict)

        # Save to file if requested
        if output:
            with open(output, "w") as f:
                json.dump(result_dict, f, indent=2)
            console.print(f"\n[dim]Result saved to: {output}[/]")

        # Return appropriate exit code
        if result.passed:
            console.print(f"\n[bold green]ASSERTION PASSED[/]")
            raise typer.Exit(0)
        else:
            console.print(f"\n[bold red]ASSERTION FAILED[/]")
            raise typer.Exit(1)

    except Exception as e:
        console.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(1)
    finally:
        await browser.close()


def _print_assertion_result(assertion: str, result: dict):
    """Print assertion result to console."""
    table = Table(title="Assertion Result")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")

    passed = result.get("passed", False)
    status_style = "green" if passed else "red"

    table.add_row("Assertion", assertion)
    table.add_row("Status", f"[{status_style}]{'PASSED' if passed else 'FAILED'}[/]")
    table.add_row("Actual", str(result.get("actual_value", "N/A")))
    table.add_row("Expected", str(result.get("expected_value", "N/A")))

    if result.get("error"):
        table.add_row("Error", result["error"])

    console.print(table)


if __name__ == "__main__":
    app()
