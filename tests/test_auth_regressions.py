"""Authentication and secret-handling tests; no browser or provider is started."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from auth.manager import AuthManager
from auth.policies import LoginPolicy
from auth.redaction import SecretRedactor, resolve_secret_references
from config import config


@pytest.fixture
def policy():
    return LoginPolicy(
        domain="example.test",
        service="AUDIT_TEST",
        login_url="https://example.test/login",
        username_selector="#username",
        password_selector="#password",
        submit_selector="#submit",
        post_login_selector="#account-menu",
    )


@pytest.fixture
def browser():
    page = SimpleNamespace(
        url="https://example.test/login",
        locator=MagicMock(),
        wait_for_selector=AsyncMock(),
    )
    page.locator.return_value.first.is_visible = AsyncMock(return_value=False)
    return SimpleNamespace(
        page=page,
        navigate=AsyncMock(return_value=True),
        type_text=AsyncMock(return_value=True),
        click=AsyncMock(return_value=True),
    )


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setattr(config.auth, "enable_login_policies", True)
    monkeypatch.setenv("AUDIT_TEST_USERNAME", "synthetic-user")
    monkeypatch.setenv("AUDIT_TEST_PASSWORD", "synthetic-password")


@pytest.mark.asyncio
async def test_empty_saved_state_does_not_prove_login(
    policy, browser, tmp_path, monkeypatch
):
    state = tmp_path / "state.json"
    state.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    monkeypatch.setattr(config.browser, "reuse_storage_state", True)
    monkeypatch.setattr(config.browser, "storage_state_path", str(state))
    manager = AuthManager({policy.domain: policy})

    assert not await manager.ensure_logged_in(browser, "https://example.test/")
    browser.navigate.assert_awaited_once_with(policy.login_url)
    assert browser.type_text.await_count == 2


@pytest.mark.asyncio
async def test_verified_current_session_skips_login_without_reading_credentials(
    policy, browser, monkeypatch
):
    browser.page.locator.return_value.first.is_visible.return_value = True
    getter = MagicMock(side_effect=AssertionError("credentials must not be read"))
    monkeypatch.setattr(config, "get_credential", getter)
    manager = AuthManager({policy.domain: policy})

    assert await manager.ensure_logged_in(browser, "https://example.test/")
    browser.navigate.assert_not_awaited()
    browser.type_text.assert_not_awaited()
    getter.assert_not_called()


@pytest.mark.asyncio
async def test_selector_on_unrelated_domain_does_not_authenticate(policy, browser):
    browser.page.url = "https://unrelated.test/login"
    browser.page.locator.return_value.first.is_visible.return_value = True
    manager = AuthManager({policy.domain: policy})

    assert not await manager.ensure_logged_in(browser, "https://example.test/")
    browser.type_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_login_navigation_never_enters_credentials(policy, browser):
    browser.navigate.return_value = False
    manager = AuthManager({policy.domain: policy})

    assert not await manager.ensure_logged_in(browser, "https://example.test/")
    browser.type_text.assert_not_awaited()
    browser.click.assert_not_awaited()


@pytest.mark.asyncio
async def test_unexpected_login_redirect_never_enters_credentials(policy, browser):
    async def redirected(_url):
        browser.page.url = "https://unrelated.test/login"
        return True

    browser.navigate.side_effect = redirected
    manager = AuthManager({policy.domain: policy})

    assert not await manager.ensure_logged_in(browser, "https://example.test/")
    browser.type_text.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("selector", [None, "", "body", "html", "*", "body, #account"])
async def test_generic_postconditions_do_not_authorize_login(policy, browser, selector):
    manager = AuthManager(
        {policy.domain: replace(policy, post_login_selector=selector)}
    )
    assert not await manager.ensure_logged_in(browser, "https://example.test/")
    browser.navigate.assert_not_awaited()
    browser.type_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_username_fill_stops_before_password_or_submit(policy, browser):
    browser.type_text.return_value = False
    manager = AuthManager({policy.domain: policy})

    assert not await manager.ensure_logged_in(browser, "https://example.test/")
    browser.type_text.assert_awaited_once_with("#username", "synthetic-user")
    browser.click.assert_not_awaited()


@pytest.mark.asyncio
async def test_login_success_requires_postcondition_and_registers_credentials(
    policy, browser
):
    browser.page.locator.return_value.first.is_visible.side_effect = [False, True]
    redactor = SecretRedactor()
    manager = AuthManager({policy.domain: policy}, redactor=redactor)

    assert await manager.ensure_logged_in(browser, "https://example.test/")
    browser.page.wait_for_selector.assert_awaited_once_with(
        "#account-menu", state="visible", timeout=config.browser.timeout_seconds * 1000
    )
    assert redactor.redact("synthetic-user synthetic-password") == (
        "${ENV:AUDIT_TEST_USERNAME} ${ENV:AUDIT_TEST_PASSWORD}"
    )


@pytest.mark.asyncio
async def test_login_timeout_does_not_log_secret_exception(policy, browser, caplog):
    browser.page.wait_for_selector.side_effect = RuntimeError("synthetic-password")
    manager = AuthManager({policy.domain: policy})

    assert not await manager.ensure_logged_in(browser, "https://example.test/")
    assert "synthetic-password" not in caplog.text


@pytest.mark.asyncio
async def test_empty_policy_dictionary_disables_default_policy(browser):
    assert not await AuthManager({}).ensure_logged_in(browser, "https://example.com/")
    browser.type_text.assert_not_awaited()


def test_redaction_covers_nested_results_and_encoded_urls():
    redactor = SecretRedactor()
    redactor.add("synthetic secret&value", replacement="${ENV:TEST_SECRET}")
    result = redactor.redact(
        {
            "task": "Enter synthetic secret&value",
            "actions": [{"error": "failed synthetic secret&value"}],
            "url": "https://example.test/?p=synthetic%20secret%26value",
            "form": ("synthetic+secret%26value", None, 3),
        }
    )
    assert result["task"] == "Enter ${ENV:TEST_SECRET}"
    assert result["actions"][0]["error"] == "failed ${ENV:TEST_SECRET}"
    assert result["url"] == "https://example.test/?p=${ENV:TEST_SECRET}"
    assert result["form"] == ("${ENV:TEST_SECRET}", None, 3)


def test_overlapping_secret_replacements_are_not_recursively_corrupted():
    redactor = SecretRedactor()
    redactor.add("secret", replacement="${ENV:secret}")
    redactor.add("secret-long", replacement="${ENV:LONG}")
    assert redactor.redact("secret-long secret") == "${ENV:LONG} ${ENV:secret}"
    assert redactor.redact("${ENV:LONG} ${ENV:secret}") == "${ENV:LONG} ${ENV:secret}"


def test_redaction_preserves_result_schema_and_action_commands():
    redactor = SecretRedactor()
    for secret in ["success", "action", "TYPE", "fake"]:
        redactor.add(secret)
    result = redactor.redact(
        {
            "status": "success",
            "model": "fake",
            "type": "TYPE",
            "actions": [{"action": "TYPE:#input:success", "status": "success"}],
            "error": "action failed: success",
        }
    )
    assert result["status"] == "success"
    assert result["model"] == "fake"
    assert result["type"] == "TYPE"
    assert result["actions"] == [
        {"action": "TYPE:#input:[REDACTED]", "status": "success"}
    ]
    assert result["error"] == "[REDACTED] failed: [REDACTED]"


def test_json_actions_preserve_schema_and_redact_payload():
    redactor = SecretRedactor()
    redactor.add("TYPE")
    redactor.add("synthetic-password")
    result = redactor.redact(
        {"action": json.dumps({"type": "TYPE", "text": "synthetic-password"})}
    )
    assert json.loads(result["action"]) == {"type": "TYPE", "text": "[REDACTED]"}
    assert redactor.redact({"action": "synthetic-password"}) == {"action": "[REDACTED]"}


def test_requires_login_distinguishes_unconfigured_and_disabled_targets(
    policy, monkeypatch
):
    manager = AuthManager({policy.domain: policy})
    assert manager.requires_login("https://example.test/")
    assert not manager.requires_login("https://other.test/")
    monkeypatch.setattr(config.auth, "enable_login_policies", False)
    assert not manager.requires_login("https://example.test/")


def test_example_policy_does_not_require_credentials_by_default():
    assert not AuthManager().requires_login("https://example.com/")


def test_resolve_environment_reference_registers_value_and_preserves_reference(
    monkeypatch,
):
    monkeypatch.setenv("ONLY_SYNTHETIC_SECRET", "synthetic-secret-value")
    redactor = SecretRedactor()
    text = resolve_secret_references("prefix ${ENV:ONLY_SYNTHETIC_SECRET}", redactor)
    assert text == "prefix synthetic-secret-value"
    redactor.add("synthetic-secret-value")
    assert redactor.redact(text) == "prefix ${ENV:ONLY_SYNTHETIC_SECRET}"


def test_missing_environment_reference_fails_without_dumping_environment(monkeypatch):
    monkeypatch.delenv("MISSING_AUDIT_SECRET", raising=False)
    with pytest.raises(
        ValueError, match="Missing secret environment variable: MISSING_AUDIT_SECRET"
    ):
        resolve_secret_references("${ENV:MISSING_AUDIT_SECRET}", SecretRedactor())
