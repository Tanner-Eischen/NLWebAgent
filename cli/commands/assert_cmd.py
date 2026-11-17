"""
nlwa assert - DOM assertions on web pages.

Usage:
    nlwa assert "price < 50" --url https://shop.example.com/product/123
    nlwa assert "title contains 'Welcome'" --url https://example.com
    nlwa assert "button is visible" --selector "#submit" --url https://example.com
"""

import asyncio
import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from auth.redaction import SecretRedactor
from browser.playwright_agent import BrowserController
from cli.assertions.evaluator import AssertionEvaluator
from cli.assertions.parser import parse_assertion

app = typer.Typer(
    context_settings={"allow_interspersed_args": True},
    help="Run DOM assertions on web pages",
)
console = Console()


@app.callback(invoke_without_command=True)
def assert_cmd(
    assertion: str = typer.Argument(
        ..., help="Assertion expression (e.g., 'price < 50')"
    ),
    url: str = typer.Option(..., "--url", "-u", help="URL to assert against"),
    selector: Optional[str] = typer.Option(
        None, "--selector", "-s", help="CSS selector for target element"
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output file for assertion result"
    ),
    headless: Optional[bool] = typer.Option(
        None,
        "--headless/--headed",
        "-h/-H",
        help="Override configured browser display mode",
    ),
):
    """
    Run a DOM assertion against a web page.

    Supported assertion types:
    - Numeric comparisons: "price < 50", "count >= 5"
    - String matching: "title contains 'Sale'", "url starts with 'https'"
    - Visibility checks: "button is visible", "form is hidden"

    Example:
        nlwa assert "price < 50" --url https://shop.example.com/product/123
    """
    asyncio.run(_assert_async(assertion, url, selector, output, headless))


async def _assert_async(
    assertion: str,
    url: str,
    selector: Optional[str],
    output: Optional[Path],
    headless: Optional[bool],
):
    """Evaluate a page assertion and preserve its verdict as the process exit code."""
    redactor = SecretRedactor()
    browser = None
    try:
        parsed = parse_assertion(assertion)
        if selector:
            parsed.selector = selector
        browser = BrowserController(headless=headless)
        redactor = browser.redactor
        try:
            await browser.create_session()
            if not await browser.navigate(url):
                raise RuntimeError(browser.last_error or "Navigation failed")
            result = await AssertionEvaluator(browser).evaluate(parsed)
        finally:
            await browser.close()

        result_dict = result.to_dict()
        result_dict["assertion"] = assertion
        result_dict["selector"] = selector
        result_dict = redactor.redact(result_dict)
        _print_assertion_result(redactor.redact(assertion), result_dict)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            with open(output, "w", encoding="utf-8") as f:
                json.dump(result_dict, f, indent=2)
            console.print(f"\n[dim]Result saved to: {output}[/]")
        exit_code = 0 if result.passed else 1
        console.print("\nASSERTION PASSED" if result.passed else "\nASSERTION FAILED")
    except Exception as e:
        console.print(f"[bold red]Error:[/] {redactor.redact(str(e))}")
        exit_code = 1
    raise typer.Exit(exit_code)


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
