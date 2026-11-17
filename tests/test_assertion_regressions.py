"""Assertion correctness tests using fake pages; no browser is started."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cli.assertions.evaluator import AssertionEvaluator
from cli.assertions.parser import parse_assertion


@pytest.mark.parametrize(
    "expression", ["#target is hidden", "count(.item) == 0", "#target exists"]
)
async def test_query_failure_never_passes(expression):
    page = MagicMock()
    page.locator.side_effect = RuntimeError("page closed")
    result = await AssertionEvaluator(SimpleNamespace(page=page)).evaluate(
        parse_assertion(expression)
    )
    assert not result.passed
    assert result.error == "page closed"


async def test_valid_zero_matches_can_pass():
    page = MagicMock()
    page.locator.return_value.count = AsyncMock(return_value=0)
    result = await AssertionEvaluator(SimpleNamespace(page=page)).evaluate(
        parse_assertion("count(.item) == 0")
    )
    assert result.passed
    assert result.actual_value == 0
    assert result.error is None


@pytest.mark.parametrize(
    "text, expected",
    [("-$20", -20), ("$-20.25", -20.25), ("−£1,234.50", -1234.5), ("+€5", 5)],
)
async def test_signed_currency_values(text, expected):
    browser = SimpleNamespace(extract=AsyncMock(return_value=(True, text)))
    result = await AssertionEvaluator(browser).evaluate(
        parse_assertion(f"price == {expected}")
    )
    assert result.passed
    assert result.actual_value == expected


@pytest.mark.parametrize(
    "text", ["1,25", "1.234,56", "$20 - $30", "two prices: 20 and 30"]
)
async def test_ambiguous_number_fails(text):
    browser = SimpleNamespace(extract=AsyncMock(return_value=(True, text)))
    result = await AssertionEvaluator(browser).evaluate(parse_assertion("price > 0"))
    assert not result.passed
    assert result.error


@pytest.mark.parametrize(
    "expression",
    [
        "price > 0",
        "title contains 'Ready'",
        "button is visible",
        "form exists",
        "count(.item) >= 1",
    ],
)
async def test_selector_override_reaches_actual_query(expression):
    page = MagicMock()
    page.locator.return_value.first.is_visible = AsyncMock(return_value=True)
    page.locator.return_value.count = AsyncMock(return_value=1)
    browser = SimpleNamespace(
        page=page, extract=AsyncMock(return_value=(True, "Ready"))
    )
    assertion = parse_assertion(expression)
    assertion.selector = "#specific"
    await AssertionEvaluator(browser).evaluate(assertion)
    if browser.extract.await_count:
        browser.extract.assert_awaited_once_with("#specific", "text")
    else:
        page.locator.assert_called_once_with("#specific")


@pytest.mark.parametrize(
    "expression",
    ["", "verify checkout succeeded", "price < NaN", "price > 0 trailing text"],
)
def test_unsupported_expression_is_rejected(expression):
    with pytest.raises(ValueError, match="Unsupported assertion"):
        parse_assertion(expression)
