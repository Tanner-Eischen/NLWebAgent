"""Controller regressions using fake pages only; no browser is launched."""

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from browser.playwright_agent import BrowserController
from config import config


@pytest.fixture
def browser():
    controller = BrowserController("synthetic-session")
    controller.page = SimpleNamespace(
        viewport_size={"width": 1280, "height": 720},
        mouse=SimpleNamespace(click=AsyncMock()),
        keyboard=SimpleNamespace(type=AsyncMock()),
        fill=AsyncMock(),
        type=AsyncMock(),
        click=AsyncMock(),
        eval_on_selector=AsyncMock(return_value="synthetic-value"),
    )
    controller._resolve_selector = AsyncMock(side_effect=lambda selector: selector)
    return controller


def test_constructor_overrides_do_not_mutate_global_config(monkeypatch):
    monkeypatch.setattr(config.browser, "headless", False)
    monkeypatch.setattr(config.browser, "record_video", True)
    controller = BrowserController(headless=True, record_video=False)
    assert controller.headless is True
    assert controller.record_video is False
    assert config.browser.headless is False
    assert config.browser.record_video is True
    defaults = BrowserController()
    assert defaults.headless is False
    assert defaults.record_video is True


@pytest.mark.asyncio
async def test_disabled_video_is_not_passed_to_context(monkeypatch):
    monkeypatch.setattr(config.browser, "reuse_storage_state", False)
    controller = BrowserController(record_video=False)
    fake_page = MagicMock()
    fake_context = SimpleNamespace(new_page=AsyncMock(return_value=fake_page))
    controller.browser = SimpleNamespace(
        new_context=AsyncMock(return_value=fake_context)
    )
    await controller.create_session()
    assert "record_video_dir" not in controller.browser.new_context.call_args.kwargs


@pytest.mark.asyncio
async def test_type_executes_real_value_and_redacts_transcript(browser, caplog):
    secret = "synthetic-private-input"
    caplog.set_level(logging.INFO)
    selector = f'input[data-name="{secret}"]'
    assert await browser.type_text(selector, secret)
    browser.page.type.assert_awaited_once_with(selector, secret, delay=50)
    assert browser.transcript[-1]["text"] == "[REDACTED]"
    assert secret not in json.dumps(browser.transcript)
    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_missing_selector_logs_and_errors_are_redacted(browser, caplog):
    browser._resolve_selector.side_effect = None
    browser._resolve_selector.return_value = None
    secret = "synthetic-private-input"
    assert not await browser.type_text(f'input[name="{secret}"]', secret)
    assert secret not in browser.last_error
    assert secret not in caplog.text
    browser.page.type.assert_not_awaited()


@pytest.mark.asyncio
async def test_typing_exception_does_not_expose_value(browser, caplog):
    secret = "synthetic-private-input"
    browser.page.type.side_effect = RuntimeError(f"failed while typing {secret}")
    assert not await browser.type_text("#password", secret)
    assert secret not in browser.last_error
    assert secret not in caplog.text
    assert browser.transcript == []


@pytest.mark.asyncio
async def test_exact_environment_reference_remains_replayable(browser, monkeypatch):
    monkeypatch.setenv("SYNTHETIC_BROWSER_SECRET", "synthetic-private-input")
    reference = "${ENV:SYNTHETIC_BROWSER_SECRET}"
    assert await browser.type_text("#password", reference)
    browser.page.type.assert_awaited_once_with(
        "#password", "synthetic-private-input", delay=50
    )
    assert browser.transcript[-1]["text"] == reference


@pytest.mark.asyncio
async def test_registered_auth_credential_keeps_environment_reference(browser):
    secret = "synthetic-auth-password"
    reference = "${ENV:AUTH_PASSWORD}"
    browser.redactor.add(secret, replacement=reference)
    assert await browser.type_text("#password", secret)
    assert browser.transcript[-1]["text"] == reference


@pytest.mark.asyncio
async def test_mixed_literal_and_environment_reference_are_fully_masked(
    browser, monkeypatch
):
    monkeypatch.setenv("SYNTHETIC_BROWSER_SECRET", "synthetic-private-input")
    raw = "private-prefix ${ENV:SYNTHETIC_BROWSER_SECRET} private-suffix"
    actual = "private-prefix synthetic-private-input private-suffix"
    assert await browser.type_text("#password", raw)
    browser.page.type.assert_awaited_once_with("#password", actual, delay=50)
    assert browser.transcript[-1]["text"] == "[REDACTED]"
    assert (
        browser.redactor.redact(f"Error typing {actual}") == "Error typing [REDACTED]"
    )


@pytest.mark.asyncio
async def test_coordinate_execution_records_pixels_and_viewport(browser):
    assert await browser.click_at(0.5, 0.25)
    browser.page.mouse.click.assert_awaited_once_with(640, 180)
    assert browser.transcript[-1] == {
        "action": "click_at",
        "x": 640,
        "y": 180,
        "coordinate_space": "pixels",
        "viewport": {"width": 1280, "height": 720},
    }


@pytest.mark.asyncio
async def test_coordinate_typing_redacts_input_and_keeps_pixel_metadata(browser):
    assert await browser.type_at(0.5, 0.25, "synthetic-private-input")
    browser.page.keyboard.type.assert_awaited_once_with(
        "synthetic-private-input", delay=50
    )
    assert browser.transcript[-1]["text"] == "[REDACTED]"
    assert browser.transcript[-1]["x"] == 640
    assert browser.transcript[-1]["coordinate_space"] == "pixels"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["click", "extract"])
async def test_known_secret_in_selector_never_appears_in_logs(
    browser, caplog, operation
):
    secret = "synthetic-private-input"
    browser.redactor.add(secret)
    caplog.set_level(logging.INFO)
    selector = f'input[data-name="{secret}"]'
    if operation == "click":
        assert await browser.click(selector)
    else:
        ok, _ = await browser.extract(selector, "value")
        assert ok
    assert secret not in caplog.text
    assert secret not in json.dumps(browser.transcript)


def test_transcript_persistence_redacts_previously_recorded_values(
    browser, tmp_path, monkeypatch
):
    monkeypatch.setattr(config.browser, "transcript_dir", str(tmp_path))
    browser.transcript.append({"action": "extract", "value": "synthetic-private-input"})
    browser.redactor.add("synthetic-private-input")
    path = browser.save_transcript()
    with open(path, encoding="utf-8") as saved:
        data = json.load(saved)
    assert data[0]["value"] == "[REDACTED]"
