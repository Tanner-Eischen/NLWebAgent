"""
Deterministic tests using HTML fixtures and a fake model.

These tests validate the agent workflow without requiring a real LLM.
"""
import asyncio
from pathlib import Path
from typing import Optional, List
from unittest.mock import AsyncMock

import pytest

from agent.actions import ActionType, parse_action
from agent.orchestrator import WebAutomationAgent
from browser.playwright_agent import BrowserController
from models.base_model import AIModel


class FakeDeterministicModel(AIModel):
    """
    A fake model that returns predetermined actions for testing.

    SCENARIOS define action sequences for different test cases:
    - "search": Click search box, type query, click search button
    - "login": Fill username, fill password, click login
    - "extract": Extract data from table
    """

    SCENARIOS = {
        "search": [
            "CLICK:#search-box",
            "TYPE:#search-box:test query",
            "CLICK:#search-btn",
            "DONE",
        ],
        "login": [
            "CLICK:#username",
            "TYPE:#username:testuser",
            "CLICK:#password",
            "TYPE:#password:testpass",
            "CLICK:#login-btn",
            "DONE",
        ],
        "extract": [
            "EXTRACT:.name:text",
            "EXTRACT:.price:text",
            "DONE",
        ],
        "click_at_search": [
            "CLICK_AT:0.5:0.2",
            "TYPE_AT:0.5:0.2:test",
            "CLICK_AT:0.9:0.2",
            "DONE",
        ],
    }

    def __init__(self, scenario: str = "search"):
        super().__init__()
        self.scenario = scenario
        self.action_index = 0
        self.actions = self.SCENARIOS.get(scenario, self.SCENARIOS["search"])

    async def analyze_screenshot(self, screenshot_path: str, prompt: str) -> str:
        return f"Analyzed {screenshot_path}: {prompt[:50]}..."

    async def reason(self, context: str, prompt: str) -> str:
        return f"Reasoning about: {prompt[:50]}..."

    async def decide_next_action(
        self,
        screenshot_path: str,
        task: str,
        history: Optional[str] = None,
        error_hint: Optional[str] = None,
    ) -> str:
        """Return the next predetermined action in the sequence."""
        if self.action_index >= len(self.actions):
            return "DONE"

        action = self.actions[self.action_index]
        self.action_index += 1
        return action

    def reset(self, scenario: Optional[str] = None):
        """Reset to start of scenario or switch to new scenario."""
        if scenario:
            self.scenario = scenario
            self.actions = self.SCENARIOS.get(scenario, self.SCENARIOS["search"])
        self.action_index = 0


class FakeModelSelector:
    """Fake model selector that uses FakeDeterministicModel."""

    def __init__(self, scenario: str = "search"):
        self.model = FakeDeterministicModel(scenario)

    async def decide_next_action_with_fallback(
        self, screenshot_path: str, task: str, history: str = None, error_hint: str = None, dom_context: str = None,
    ) -> tuple:
        action = await self.model.decide_next_action(screenshot_path, task, history, error_hint)
        return action, "fake_model"


    async def close(self):
        pass


@pytest.fixture
def fixtures_dir():
    """Return path to fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def search_html(fixtures_dir):
    """Return file:// URL for search fixture."""
    return (fixtures_dir / "search.html").as_uri()


@pytest.fixture
def login_html(fixtures_dir):
    """Return file:// URL for login fixture."""
    return (fixtures_dir / "login_form.html").as_uri()


@pytest.fixture
def data_table_html(fixtures_dir):
    """Return file:// URL for data table fixture."""
    return (fixtures_dir / "data_table.html").as_uri()


@pytest.mark.asyncio
async def test_search_workflow(search_html):
    """Test the search workflow with deterministic actions."""
    model_selector = FakeModelSelector("search")
    browser = BrowserController("test_search")

    try:
        await browser.create_session()

        agent = WebAutomationAgent(
            session_id="test_search",
            model_selector=model_selector,
            browser=browser,
        )

        result = await agent.execute_task(
            task_description="Search for 'test query'",
            start_url=search_html,
            max_steps=10,
        )

        assert result["status"] == "success", f"Expected success, got {result['status']}"
        assert len(result["actions"]) >= 3, "Should have at least 3 actions"
        assert result["steps_taken"] >= 3

        # Check that selector actions were executed
        action_types = [a.get("action", "").split(":")[0] for a in result["actions"]]
        assert "CLICK" in action_types or "TYPE" in action_types

    finally:
        await browser.close()


@pytest.mark.asyncio
async def test_login_workflow(login_html):
    """Test the login workflow with deterministic actions."""
    model_selector = FakeModelSelector("login")
    browser = BrowserController("test_login")

    try:
        await browser.create_session()

        agent = WebAutomationAgent(
            session_id="test_login",
            model_selector=model_selector,
            browser=browser,
        )

        result = await agent.execute_task(
            task_description="Login with username 'testuser' and password 'testpass'",
            start_url=login_html,
            max_steps=10,
        )

        assert result["status"] == "success", f"Expected success, got {result['status']}"
        assert len(result["actions"]) >= 5, "Should have at least 5 actions"

    finally:
        await browser.close()


@pytest.mark.asyncio
async def test_extract_workflow(data_table_html):
    """Test the extract workflow with deterministic actions."""
    model_selector = FakeModelSelector("extract")
    browser = BrowserController("test_extract")

    try:
        await browser.create_session()

        agent = WebAutomationAgent(
            session_id="test_extract",
            model_selector=model_selector,
            browser=browser,
        )

        result = await agent.execute_task(
            task_description="Extract product names and prices",
            start_url=data_table_html,
            max_steps=10,
        )

        assert result["status"] == "success", f"Expected success, got {result['status']}"

        # Check extractions were collected
        assert len(result["extractions"]) >= 1, "Should have extractions"

    finally:
        await browser.close()


@pytest.mark.asyncio
async def test_click_at_fallback_workflow(search_html):
    """Test coordinate-based actions when selectors might fail."""
    model_selector = FakeModelSelector("click_at_search")
    browser = BrowserController("test_click_at")

    try:
        await browser.create_session()

        agent = WebAutomationAgent(
            session_id="test_click_at",
            model_selector=model_selector,
            browser=browser,
        )

        result = await agent.execute_task(
            task_description="Click and type using coordinates",
            start_url=search_html,
            max_steps=10,
        )

        assert result["status"] == "success", f"Expected success, got {result['status']}"

        # Verify coordinate actions were executed
        actions = result["actions"]
        click_at_actions = [a for a in actions if "CLICK_AT" in a.get("action", "")]
        type_at_actions = [a for a in actions if "TYPE_AT" in a.get("action", "")]
        assert len(click_at_actions) >= 1, "Should have CLICK_AT actions"

    finally:
        await browser.close()


@pytest.mark.asyncio
async def test_browser_extract_method(data_table_html):
    """Test browser extract method directly."""
    browser = BrowserController("test_extract_method")

    try:
        await browser.create_session()
        await browser.navigate(data_table_html)

        # Test extracting text from tbody (excludes header)
        ok, value = await browser.extract("tbody .name", "text")
        assert ok, f"Extract should succeed, error: {browser.last_error}"
        assert value is not None
        assert "Widget A" in value

        # Test extracting price from tbody
        ok, price = await browser.extract("tbody .price", "text")
        assert ok
        assert "$" in price

    finally:
        await browser.close()


@pytest.mark.asyncio
async def test_browser_extract_all_method(data_table_html):
    """Test browser extract_all method."""
    browser = BrowserController("test_extract_all")

    try:
        await browser.create_session()
        await browser.navigate(data_table_html)

        # Extract all product names from tbody (excludes header row)
        ok, values = await browser.extract_all("tbody .name", "text")
        assert ok, f"Extract all should succeed, error: {browser.last_error}"
        assert len(values) == 5, f"Should have 5 products, got {len(values)}"
        assert "Widget A" in values
        assert "Gadget B" in values

        # Extract all prices from tbody
        ok, prices = await browser.extract_all("tbody .price", "text")
        assert ok
        assert len(prices) == 5

    finally:
        await browser.close()


@pytest.mark.asyncio
async def test_action_parsing():
    """Test that action parsing works correctly for all action types."""
    # Test CLICK
    action = parse_action("CLICK:#my-button")
    assert action.type == ActionType.CLICK
    assert action.selector == "#my-button"

    # Test TYPE
    action = parse_action("TYPE:#search-box:hello world")
    assert action.type == ActionType.TYPE
    assert action.selector == "#search-box"
    assert action.text == "hello world"

    # Test EXTRACT
    action = parse_action("EXTRACT:.price:text")
    assert action.type == ActionType.EXTRACT
    assert action.selector == ".price"
    assert action.attr == "text"

    # Test CLICK_AT
    action = parse_action("CLICK_AT:0.5:0.3")
    assert action.type == ActionType.CLICK_AT
    assert action.x == 0.5
    assert action.y == 0.3

    # Test TYPE_AT
    action = parse_action("TYPE_AT:0.5:0.3:test text")
    assert action.type == ActionType.TYPE_AT
    assert action.x == 0.5
    assert action.y == 0.3
    assert action.text == "test text"

    # Test DONE
    action = parse_action("DONE")
    assert action.type == ActionType.DONE


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
