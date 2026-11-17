"""Regression tests for execution control flow; all browser/model calls are fakes."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.orchestrator import WebAutomationAgent
from auth.manager import AuthManager
from auth.redaction import SecretRedactor
from config import config


@pytest.fixture
def setup_agent(monkeypatch):
    monkeypatch.setattr(config.agent, "auto_checkboxes", False)
    monkeypatch.setattr(config.agent, "pause_on_captcha", False)

    def create(actions):
        browser = SimpleNamespace(
            page=SimpleNamespace(url="https://example.invalid/"),
            last_error=None,
            transcript=[],
            navigate=AsyncMock(return_value=True),
            click=AsyncMock(return_value=True),
            click_at=AsyncMock(return_value=True),
            type_text=AsyncMock(return_value=True),
            type_at=AsyncMock(return_value=True),
            get_dom_context=AsyncMock(return_value=""),
            take_screenshot=AsyncMock(return_value="mock.png"),
            detect_captcha=AsyncMock(return_value=False),
            click_first_checkbox=AsyncMock(return_value=False),
            close=AsyncMock(
                return_value={"videos": ["final.webm"], "transcript": "final.json"}
            ),
        )
        model = SimpleNamespace(
            decide_next_action_with_fallback=AsyncMock(
                side_effect=[(a, "fake") for a in actions]
            ),
            analyze_screenshot_with_fallback=AsyncMock(
                return_value=("0.25:0.75", "fake")
            ),
            close=AsyncMock(),
        )
        auth = SimpleNamespace(
            redactor=SecretRedactor(), ensure_logged_in=AsyncMock(return_value=False)
        )
        agent = WebAutomationAgent(
            browser=browser, model_selector=model, auth_manager=auth
        )
        agent.max_retries = 1
        return agent, browser, model

    return create


@pytest.mark.asyncio
async def test_quoted_task_executes_click_before_done(setup_agent):
    agent, browser, model = setup_agent(["CLICK_AT:0.5:0.5", "DONE"])
    result = await agent.execute_task("Search for 'query'", max_steps=2)
    browser.click_at.assert_awaited_once_with(0.5, 0.5)
    browser.type_at.assert_not_awaited()
    assert result["status"] == "success"
    assert result["outcome"] == "unverified"
    assert result["steps_taken"] == 2


@pytest.mark.asyncio
async def test_error_is_terminal_even_if_model_would_later_say_done(setup_agent):
    agent, browser, model = setup_agent(["ERROR:cannot complete", "DONE"])
    result = await agent.execute_task("Do task")
    assert result["status"] == "failed"
    assert result["errors"] == ["cannot complete"]
    assert model.decide_next_action_with_fallback.await_count == 1


@pytest.mark.asyncio
async def test_navigation_to_distinct_page_allowed(setup_agent):
    agent, browser, model = setup_agent(
        ["NAVIGATE:https://example.invalid/next", "DONE"]
    )
    result = await agent.execute_task(
        "Go next", start_url="https://example.invalid/", max_steps=2
    )
    assert result["status"] == "success"
    assert browser.navigate.await_count == 2
    browser.navigate.assert_awaited_with("https://example.invalid/next")


@pytest.mark.asyncio
async def test_redundant_navigation_is_bounded(setup_agent):
    agent, browser, model = setup_agent(["NAVIGATE:https://example.invalid/"] * 2)
    result = await agent.execute_task("Go again", max_steps=10)
    assert result["status"] == "failed"
    browser.navigate.assert_not_awaited()
    assert model.decide_next_action_with_fallback.await_count == 2


@pytest.mark.asyncio
async def test_captcha_detection_independent_of_auto_checkboxes(
    setup_agent, monkeypatch
):
    agent, browser, model = setup_agent(["DONE"])
    monkeypatch.setattr(config.agent, "pause_on_captcha", True)
    browser.detect_captcha.return_value = True
    result = await agent.execute_task("Check page")
    assert result["status"] == "paused_for_captcha"
    model.decide_next_action_with_fallback.assert_not_awaited()
    browser.click_first_checkbox.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_selector_uses_supported_vision_api_and_actual_event(setup_agent):
    agent, browser, model = setup_agent(["CLICK:#missing", "DONE"])
    browser.click.return_value = False
    browser.last_error = "Selector not found: #missing"

    async def click_at(x, y):
        browser.transcript.append(
            {"action": "click_at", "x": 320, "y": 540, "coordinate_space": "pixels"}
        )
        browser.last_error = None
        return True

    browser.click_at.side_effect = click_at
    result = await agent.execute_task("Click target", max_steps=2)
    browser.click_at.assert_awaited_once_with(0.25, 0.75)
    model.analyze_screenshot_with_fallback.assert_awaited_once()
    assert result["executed_actions"][0]["action"] == "click_at"
    assert result["status"] == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text", ["SYNTHETIC-password-123", "success", "TYPE", "action"]
)
async def test_typed_values_redacted_without_corrupting_action_schema(
    setup_agent, text
):
    agent, browser, model = setup_agent(
        [json.dumps({"type": "TYPE", "selector": "#password", "text": text}), "DONE"]
    )
    result = await agent.execute_task("Fill form", max_steps=2)
    browser.type_text.assert_awaited_once_with("#password", text)
    assert result["status"] == "success"
    action = result["actions"][0]["parsed_action"]
    assert action == {"type": "TYPE", "selector": "#password", "text": "[REDACTED]"}
    assert json.loads(result["actions"][0]["action"]) == action
    assert (
        "[REDACTED]"
        in model.decide_next_action_with_fallback.call_args.kwargs["history"]
    )


@pytest.mark.asyncio
async def test_error_and_task_are_redacted_after_failed_typing(setup_agent):
    secret = "SYNTHETIC-pass-123"
    agent, browser, model = setup_agent([f"TYPE:#password:{secret}"] * 2)
    browser.type_text.return_value = False
    browser.last_error = "could not fill " + secret
    result = await agent.execute_task("Enter " + secret, max_steps=1)
    assert secret not in json.dumps(result)
    assert (
        secret
        not in model.decide_next_action_with_fallback.call_args.kwargs["error_hint"]
    )


@pytest.mark.asyncio
async def test_invalid_model_output_does_not_echo_secret(setup_agent):
    agent, browser, model = setup_agent(["TYPE:bad-sensitive-value"] * 2)
    result = await agent.execute_task("Fill form")
    assert result["status"] == "failed"
    assert "bad-sensitive-value" not in json.dumps(result)


@pytest.mark.asyncio
async def test_auth_failure_stops_model_calls(setup_agent, monkeypatch):
    agent, browser, model = setup_agent(["DONE"])
    agent.auth_manager = AuthManager()
    monkeypatch.setattr(agent.auth_manager, "requires_login", lambda url: True)
    monkeypatch.setattr(
        agent.auth_manager, "ensure_logged_in", AsyncMock(return_value=False)
    )
    result = await agent.execute_task("Login", start_url="https://example.invalid/")
    assert result["status"] == "error"
    model.decide_next_action_with_fallback.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_idempotent_and_closes_models_after_browser_failure(setup_agent):
    agent, browser, model = setup_agent(["DONE"])
    browser.close.side_effect = RuntimeError("close failed")
    with pytest.raises(RuntimeError, match="close failed"):
        await agent.close()
    await agent.close()
    browser.close.assert_awaited_once()
    model.close.assert_awaited_once()
