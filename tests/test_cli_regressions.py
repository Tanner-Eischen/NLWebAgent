"""Exercise real Typer parsing and command lifecycle using fake dependencies."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from typer.testing import CliRunner

from auth.redaction import SecretRedactor
from cli.commands import assert_cmd, record, run
from cli.commands import test as test_cmd
from cli.main import app


@pytest.fixture
def cli_dependencies(monkeypatch):
    redactor = SecretRedactor()
    browser = MagicMock()
    browser.redactor = redactor
    browser.create_session = AsyncMock()
    browser.navigate = AsyncMock(return_value=True)
    browser.close = AsyncMock(return_value={})
    browser.last_error = "navigation failed"
    browser.extract = AsyncMock(return_value=(True, "Ready"))
    browser.page.url = "https://example.invalid/done"
    browser.page.locator.return_value.first.is_visible = AsyncMock(return_value=True)
    browser.page.locator.return_value.count = AsyncMock(return_value=1)
    browser.transcript = [{"action": "navigate", "url": "https://example.invalid/"}]
    result = {
        "status": "success",
        "steps_taken": 1,
        "actions": [{"action": "DONE", "status": "success"}],
        "extractions": [],
        "errors": [],
    }
    agent = MagicMock()
    agent.redactor = redactor
    agent.initialize = AsyncMock()
    agent.execute_task = AsyncMock(return_value=result)
    agent.close = AsyncMock(
        return_value={"videos": ["final.webm"], "transcript": "final.json"}
    )
    browser_factory = MagicMock(return_value=browser)
    model_factory = MagicMock()
    for module in (run, test_cmd, record):
        monkeypatch.setattr(module, "BrowserController", browser_factory)
        monkeypatch.setattr(module, "ModelSelector", model_factory)
        monkeypatch.setattr(module, "WebAutomationAgent", MagicMock(return_value=agent))
    monkeypatch.setattr(assert_cmd, "BrowserController", browser_factory)
    generator = MagicMock(return_value="// generated test\n")
    monkeypatch.setattr(record, "generate_playwright_test", generator)
    return SimpleNamespace(
        browser=browser,
        agent=agent,
        result=result,
        browser_factory=browser_factory,
        model_factory=model_factory,
        generator=generator,
        redactor=redactor,
    )


def invoke(command, tmp_path, extra=None):
    args = {
        "run": ["run", "--task", "Do work", "--output", str(tmp_path)],
        "test": ["test", "Verify outcome", "--output", str(tmp_path)],
        "assert": ["assert", "button is visible"],
        "record": [
            "record",
            "--task",
            "Do work",
            "--output",
            str(tmp_path / "case.spec.ts"),
        ],
    }[command]
    return CliRunner().invoke(
        app, [*args, "--url", "https://example.invalid", *(extra or [])]
    )


@pytest.mark.parametrize("command", ["run", "test", "assert", "record"])
def test_success_preserves_zero_exit(command, tmp_path, cli_dependencies):
    extra = ["--expect", "title contains 'Ready'"] if command == "test" else []
    result = invoke(command, tmp_path, extra)
    assert result.exit_code == 0, result.output
    cleanup = (
        cli_dependencies.browser.close
        if command == "assert"
        else cli_dependencies.agent.close
    )
    cleanup.assert_awaited_once()
    assert "Error: 0" not in result.output


@pytest.mark.parametrize("command", ["run", "test", "assert", "record"])
def test_failure_preserves_nonzero_exit(command, tmp_path, cli_dependencies):
    cli_dependencies.result["status"] = "failed"
    cli_dependencies.browser.page.locator.return_value.first.is_visible.return_value = (
        False
    )
    result = invoke(
        command,
        tmp_path,
        ["--expect", "button is visible"] if command == "test" else [],
    )
    assert result.exit_code == 1, result.output


@pytest.mark.parametrize("command", ["run", "test", "assert", "record"])
def test_initialization_error_closes_once(command, tmp_path, cli_dependencies):
    cli_dependencies.agent.initialize.side_effect = RuntimeError(
        "initialization failed"
    )
    cli_dependencies.browser.create_session.side_effect = RuntimeError(
        "initialization failed"
    )
    result = invoke(command, tmp_path)
    assert result.exit_code == 1
    cleanup = (
        cli_dependencies.browser.close
        if command == "assert"
        else cli_dependencies.agent.close
    )
    cleanup.assert_awaited_once()


def test_no_expectations_is_unverified(tmp_path, cli_dependencies):
    result = invoke("test", tmp_path)
    assert result.exit_code == 1
    report = json.loads(
        next(tmp_path.glob("test-report_*.json")).read_text(encoding="utf-8")
    )
    assert report["status"] == "unverified"
    assert report["passed"] is False
    assert report["assertions"] == []


def test_explicit_expectations_verify_page_and_record_evidence(
    tmp_path, cli_dependencies
):
    result = invoke(
        "test",
        tmp_path,
        ["--expect", "title contains 'Ready'", "--expect", "count(.item) >= 1"],
    )
    assert result.exit_code == 0, result.output
    cli_dependencies.browser.extract.assert_awaited_once()
    report = json.loads(
        next(tmp_path.glob("test-report_*.json")).read_text(encoding="utf-8")
    )
    assert len(report["evidence"]) == 2
    assert report["evidence"][0]["actual_value"] == "Ready"
    assert report["artifacts"]["videos"] == ["final.webm"]


def test_fail_fast_stops_expectations(tmp_path, cli_dependencies):
    cli_dependencies.browser.extract.return_value = (True, "wrong")
    result = invoke(
        "test",
        tmp_path,
        [
            "--expect",
            "title contains 'Ready'",
            "--expect",
            "count(.item) >= 1",
            "--fail-fast",
        ],
    )
    assert result.exit_code == 1
    cli_dependencies.browser.page.locator.assert_not_called()


def test_run_browser_flags_are_explicit(tmp_path, cli_dependencies):
    result = invoke("run", tmp_path, ["--headless", "--no-video"])
    assert result.exit_code == 0, result.output
    cli_dependencies.browser_factory.assert_called_once_with(
        headless=True, record_video=False
    )


@pytest.mark.parametrize("command", ["run", "test", "assert", "record"])
def test_omitted_browser_flags_inherit_configuration(
    command, tmp_path, cli_dependencies
):
    extra = ["--expect", "button is visible"] if command == "test" else []
    result = invoke(command, tmp_path, extra)
    assert result.exit_code == 0, result.output
    expected = {"headless": None}
    if command in {"run", "record"}:
        expected["record_video"] = None
    cli_dependencies.browser_factory.assert_called_once_with(**expected)


@pytest.mark.parametrize("command", ["run", "test", "assert", "record"])
def test_headed_flag_overrides_configuration(command, tmp_path, cli_dependencies):
    extra = ["--headed"]
    if command == "test":
        extra.extend(["--expect", "button is visible"])
    result = invoke(command, tmp_path, extra)
    assert result.exit_code == 0, result.output
    assert cli_dependencies.browser_factory.call_args.kwargs["headless"] is False


def test_record_can_disable_video(tmp_path, cli_dependencies):
    result = invoke("record", tmp_path, ["--no-video"])
    assert result.exit_code == 0, result.output
    cli_dependencies.browser_factory.assert_called_once_with(
        headless=None, record_video=False
    )


def test_assert_selector_override_and_navigation_failure(tmp_path, cli_dependencies):
    result = invoke("assert", tmp_path, ["--selector", "#target"])
    assert result.exit_code == 0
    cli_dependencies.browser.page.locator.assert_called_once_with("#target")
    cli_dependencies.browser.navigate.return_value = False
    cli_dependencies.browser.page.locator.reset_mock()
    result = invoke("assert", tmp_path)
    assert result.exit_code == 1
    cli_dependencies.browser.page.locator.assert_not_called()


def test_run_report_contains_final_artifacts(tmp_path, cli_dependencies):
    result = invoke("run", tmp_path)
    assert result.exit_code == 0
    report = json.loads(
        next(tmp_path.glob("transcript_*.json")).read_text(encoding="utf-8")
    )
    assert report["videos"] == ["final.webm"]
    assert report["transcript"] == "final.json"


def test_manual_record_rejected_before_initialization(tmp_path, cli_dependencies):
    result = CliRunner().invoke(
        app,
        [
            "record",
            "--url",
            "https://example.invalid",
            "--output",
            str(tmp_path / "test.spec.ts"),
        ],
    )
    assert result.exit_code == 2
    assert "requires --task" in result.output
    cli_dependencies.browser_factory.assert_not_called()
    cli_dependencies.model_factory.assert_not_called()


def test_record_passes_actual_transcript_to_generator(tmp_path, cli_dependencies):
    result = invoke("record", tmp_path)
    assert result.exit_code == 0
    saved = cli_dependencies.generator.call_args.kwargs["recording"]
    assert saved["transcript"] == cli_dependencies.browser.transcript
    assert saved["artifacts"]["videos"] == ["final.webm"]


def test_record_default_name_does_not_transform_task_secrets(
    tmp_path, cli_dependencies
):
    secret = "SyNtHeTiC-pAsS!42"
    cli_dependencies.redactor.add(secret)
    result = CliRunner().invoke(
        app,
        [
            "record",
            "--task",
            f"type {secret}",
            "--url",
            "https://example.invalid",
            "--output",
            str(tmp_path / "case.spec.ts"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert cli_dependencies.generator.call_args.kwargs["test_name"] == "test_recorded"
    transformed = "syntheticpass42"
    assert secret not in result.output
    for path in tmp_path.iterdir():
        saved = path.read_text(encoding="utf-8")
        assert secret not in saved
        assert transformed not in saved


def test_explicit_record_name_is_redacted(tmp_path, cli_dependencies):
    secret = "SyNtHeTiC-pAsS!42"
    cli_dependencies.redactor.add(secret)
    result = invoke("record", tmp_path, ["--name", f"login {secret}"])
    assert result.exit_code == 0, result.output
    assert (
        cli_dependencies.generator.call_args.kwargs["test_name"] == "login [REDACTED]"
    )


@pytest.mark.parametrize("command", ["run", "test", "record"])
def test_known_secret_never_reaches_console_or_reports(
    command, tmp_path, cli_dependencies
):
    secret = "synthetic-password-123"
    cli_dependencies.redactor.add(secret)
    cli_dependencies.result["actions"] = [
        {"action": f"TYPE:#password:{secret}", "status": "success"}
    ]
    extra = ["--expect", "title contains 'Ready'"] if command == "test" else []
    result = invoke(command, tmp_path, extra)
    assert result.exit_code == 0, result.output
    assert secret not in result.output
    for path in tmp_path.iterdir():
        assert secret not in path.read_text(encoding="utf-8")


def test_known_secret_in_task_and_exception_is_redacted(tmp_path, cli_dependencies):
    secret = "synthetic-password-123"
    cli_dependencies.redactor.add(secret)
    cli_dependencies.agent.execute_task.side_effect = RuntimeError(f"failed {secret}")
    result = CliRunner().invoke(
        app,
        [
            "run",
            "--url",
            "https://example.invalid",
            "--task",
            f"type {secret}",
            "--output",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 1
    assert secret not in result.output
