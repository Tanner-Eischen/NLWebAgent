"""Browser-free diagnostic probes confirming defects at commit 5ea12fd.

These assertions document current defects, not desired regression behavior.
Run from the repository root with the editable package installed.
No browser is launched and no model/network request is made.
"""

import asyncio
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from agent.actions import parse_action  # noqa: E402
from agent.orchestrator import WebAutomationAgent  # noqa: E402
from config import config  # noqa: E402
from models.model_selector import ModelSelector  # noqa: E402


def fake_browser():
    return SimpleNamespace(
        last_error=None,
        page=SimpleNamespace(url="https://example.invalid/"),
        navigate=AsyncMock(return_value=True),
        take_screenshot=AsyncMock(return_value="mock-only-no-image.png"),
        get_dom_context=AsyncMock(return_value=""),
        click_at=AsyncMock(return_value=True),
        type_text=AsyncMock(return_value=True),
        detect_captcha=AsyncMock(return_value=True),
        click_first_checkbox=AsyncMock(return_value=True),
    )


def fake_agent(actions):
    browser = fake_browser()
    model = SimpleNamespace(
        decide_next_action_with_fallback=AsyncMock(
            side_effect=[(action, "fake") for action in actions]
        )
    )
    auth = SimpleNamespace(ensure_logged_in=AsyncMock(return_value=True))
    return WebAutomationAgent(
        browser=browser, model_selector=model, auth_manager=auth
    ), browser


async def main():
    with patch.object(config.agent, "auto_checkboxes", False):
        agent, browser = fake_agent(["CLICK_AT:0.5:0.5", "DONE"])
        result = await agent.execute_task("Search for 'query'", max_steps=1)
        assert result["status"] == "success"
        assert browser.click_at.await_count == 0
        assert result["actions"][0]["status"] == "success"
        print("CONFIRMED quoted task: CLICK_AT reported success, actual clicks=0")

        agent, browser = fake_agent(["NAVIGATE:https://example.invalid/next"])
        agent.max_retries = 0
        result = await agent.execute_task(
            "Visit the next URL", start_url="https://example.invalid/", max_steps=1
        )
        assert result["status"] == "failed"
        assert browser.navigate.await_count == 1
        print("CONFIRMED NAVIGATE to a new URL blocked after initial load")

        agent, browser = fake_agent(["DONE"])
        with patch.object(config.agent, "pause_on_captcha", True):
            result = await agent.execute_task("Check a page", max_steps=1)
        assert browser.detect_captcha.await_count == 0
        print("CONFIRMED disabling auto-checkboxes also disables CAPTCHA detection")

        sentinel = "AUDIT_SYNTHETIC_PASSWORD"
        agent, browser = fake_agent([f"TYPE:#password:{sentinel}", "DONE"])
        result = await agent.execute_task("Fill form", max_steps=2)
        assert sentinel in str(result["actions"])
        print("CONFIRMED task result retains synthetic password in raw action")

    primary = SimpleNamespace(analyze_screenshot=AsyncMock(return_value="0.5:0.5"))
    selector = ModelSelector.__new__(ModelSelector)
    selector.provider = "ollama"
    selector.ollama = primary
    selector.openai = selector.glm = selector.claude = None
    browser = fake_browser()
    agent = WebAutomationAgent(browser=browser, model_selector=selector)
    assert await agent._get_fallback_coordinates("#missing") is None
    assert primary.analyze_screenshot.await_count == 0
    print("CONFIRMED self-healing calls missing ModelSelector.model; vision calls=0")

    action = parse_action("TYPE:input:nth-of-type(2):hello")
    assert action.selector == "input"
    assert action.text == "nth-of-type(2):hello"
    extraction = parse_action("EXTRACT:li:nth-child(2):text")
    assert extraction.selector == "li"
    assert extraction.attr == "nth-child(2):text"
    print("CONFIRMED TYPE/EXTRACT colon splitting corrupts CSS pseudo-selectors")

    # Importing the test module defines its fake; it does not run its browser test.
    from tests.test_recording_artifacts import FakeModelSelector

    fake = FakeModelSelector(["DONE"])
    try:
        inspect.signature(fake.decide_next_action_with_fallback).bind(
            screenshot_path="mock", task="mock", dom_context="mock"
        )
    except TypeError as exc:
        assert "dom_context" in str(exc)
    else:
        raise AssertionError("Expected incompatible artifact-test fake")
    print("CONFIRMED artifact-test fake rejects orchestrator dom_context argument")
    print("7 diagnostic groups confirmed; no browser or model invoked")


if __name__ == "__main__":
    asyncio.run(main())
