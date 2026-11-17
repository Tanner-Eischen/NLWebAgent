"""Browser-free audit probes confirming bugs in the audited revision.

These assertions describe CURRENT BUGS, not desired regression behavior.
All browser/provider interactions are mocked; no UI or network is accessed.
Run from the repository root with: python docs/audits/2026-11-16/cli_probes.py
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import typer  # noqa: E402

from cli.assertions.evaluator import AssertionEvaluator, AssertionResult  # noqa: E402
from cli.assertions.parser import parse_assertion  # noqa: E402
from cli.codegen.generator import generate_playwright_test  # noqa: E402
from cli.commands import assert_cmd  # noqa: E402
from cli.commands.test import _generate_assertions  # noqa: E402
from config import config  # noqa: E402


async def main():
    results = {}
    browser = MagicMock()
    browser.create_session = AsyncMock()
    browser.navigate = AsyncMock(return_value=True)
    browser.close = AsyncMock()
    evaluator = MagicMock()
    evaluator.evaluate = AsyncMock(return_value=AssertionResult(True))
    before = config.browser.headless
    with (
        patch.object(assert_cmd, "BrowserController", return_value=browser),
        patch.object(assert_cmd, "AssertionEvaluator", return_value=evaluator),
        patch.object(assert_cmd.console, "print"),
    ):
        try:
            await assert_cmd._assert_async(
                "button is visible", "https://example.com", "#target", None, not before
            )
        except typer.Exit as exc:
            assert exc.exit_code == 1
            results["successful_assert_exits_failure"] = exc.exit_code
    parsed = evaluator.evaluate.call_args.args[0]
    assert parsed.selector is None and parsed.element == "button"
    results["explicit_selector_discarded"] = parsed.to_dict()
    assert config.browser.headless == before
    results["headless_flag_ignored"] = {
        "requested": not before,
        "effective": config.browser.headless,
    }

    broken = MagicMock()
    broken.page.locator.side_effect = RuntimeError("page closed or invalid selector")
    for expression in ["#missing is hidden", "count(.item) == 0"]:
        result = await AssertionEvaluator(broken).evaluate(parse_assertion(expression))
        assert result.passed and result.error is None
        results[f"query_error_passes_{expression}"] = result.to_dict()

    fake = MagicMock()
    fake.extract = AsyncMock(return_value=(True, "-$20"))
    result = await AssertionEvaluator(fake).evaluate(parse_assertion("price > 0"))
    assert result.passed and result.actual_value == 20
    results["negative_price_parsed_positive"] = result.to_dict()

    assertions = _generate_assertions(
        "Verify checkout completed",
        {"status": "success", "actions": [], "extractions": []},
    )
    assert all(item["passed"] for item in assertions)
    results["checkout_passes_without_outcome_evidence"] = assertions

    code = generate_playwright_test(
        {
            "url": "https://example.com",
            "actions": [
                {"action": "CLICK_AT:0.5:0.5", "status": "success"},
                {"action": "CLICK:#missing", "status": "failed"},
            ],
        },
        "customer's flow",
    )
    assert "page.mouse.click(0.5, 0.5)" in code
    assert "page.click('#missing')" in code
    assert "test('customer's flow'" in code
    results["codegen_coordinate_status_and_escaping_bugs"] = code

    output = Path(__file__).with_name("cli_probe_results.txt")
    output.write_text(
        "CURRENT-BUG PROBES; not desired behavior. No browser or provider calls.\n"
        + json.dumps(results, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(f"Confirmed {len(results)} diagnostic cases. Results: {output}")


if __name__ == "__main__":
    asyncio.run(main())
