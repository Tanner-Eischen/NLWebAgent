"""Provider regressions with fake clients; no network or browser access."""

import asyncio
import importlib.util
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from config import Config, config
from models.claude_model import ClaudeModel
from models.glm_model import GLMModel
from models.model_selector import ModelSelector
from models.ollama_model import OllamaModel


def selector_with(primary, fallback=None, timeout=0.01):
    selector = ModelSelector.__new__(ModelSelector)
    selector.provider = "ollama"
    selector.ollama = primary
    selector.openai = selector.glm = None
    selector.claude = fallback
    selector.fallback_to_claude = fallback is not None
    selector.timeout_seconds = timeout
    return selector


async def blocked(*args):
    await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_timeout_reaches_fallback_with_independent_deadline():
    primary = SimpleNamespace(decide_next_action=AsyncMock(side_effect=blocked))
    fallback = SimpleNamespace(decide_next_action=AsyncMock(return_value="DONE"))
    selector = selector_with(primary, fallback)
    result = await selector.decide_next_action_with_fallback("image", "task")
    assert result == ("DONE", "claude_fallback")
    fallback.decide_next_action.assert_awaited_once_with(
        "image", "task", None, None, None
    )


@pytest.mark.asyncio
async def test_fallback_also_has_a_deadline():
    primary = SimpleNamespace(decide_next_action=AsyncMock(side_effect=blocked))
    fallback = SimpleNamespace(decide_next_action=AsyncMock(side_effect=blocked))
    selector = selector_with(primary, fallback)
    with pytest.raises(asyncio.TimeoutError):
        await selector.decide_next_action_with_fallback("image", "task")
    fallback.decide_next_action.assert_awaited_once()


@pytest.mark.asyncio
async def test_primary_timeout_without_fallback_is_reported():
    selector = selector_with(
        SimpleNamespace(decide_next_action=AsyncMock(side_effect=blocked))
    )
    with pytest.raises(asyncio.TimeoutError):
        await selector.decide_next_action_with_fallback("image", "task")


@pytest.mark.asyncio
async def test_caller_cancellation_does_not_start_fallback():
    primary = SimpleNamespace(
        decide_next_action=AsyncMock(side_effect=asyncio.CancelledError)
    )
    fallback = SimpleNamespace(decide_next_action=AsyncMock(return_value="DONE"))
    selector = selector_with(primary, fallback)
    with pytest.raises(asyncio.CancelledError):
        await selector.decide_next_action_with_fallback("image", "task")
    fallback.decide_next_action.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ValueError("invalid"), asyncio.TimeoutError()])
async def test_vision_analysis_uses_same_fallback_policy(error):
    primary = SimpleNamespace(analyze_screenshot=AsyncMock(side_effect=error))
    fallback = SimpleNamespace(analyze_screenshot=AsyncMock(return_value="0.5:0.5"))
    selector = selector_with(primary, fallback)
    result = await selector.analyze_screenshot_with_fallback("image", "find button")
    assert result == ("0.5:0.5", "claude_fallback")
    fallback.analyze_screenshot.assert_awaited_once_with("image", "find button")


@pytest.mark.asyncio
async def test_primary_success_does_not_call_fallback():
    primary = SimpleNamespace(decide_next_action=AsyncMock(return_value="CLICK:#ok"))
    fallback = SimpleNamespace(decide_next_action=AsyncMock())
    result = await selector_with(primary, fallback).decide_next_action_with_fallback(
        "image", "task", "history", "error", "dom"
    )
    assert result == ("CLICK:#ok", "ollama")
    primary.decide_next_action.assert_awaited_once_with(
        "image", "task", "history", "error", "dom"
    )
    fallback.decide_next_action.assert_not_called()


@pytest.mark.asyncio
async def test_close_cleans_all_clients_despite_one_failure():
    clients = [SimpleNamespace(close=AsyncMock()) for _ in range(4)]
    clients[0].close.side_effect = RuntimeError("failure")
    selector = selector_with(clients[0], clients[3])
    selector.openai, selector.glm = clients[1:3]
    await selector.close()
    for client in clients:
        client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_does_not_close_same_client_twice():
    client = SimpleNamespace(close=AsyncMock())
    await selector_with(client, client).close()
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_glm_sync_transport_does_not_block_timeout():
    release = threading.Event()

    def create(**kwargs):
        release.wait(timeout=0.5)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="DONE"))]
        )

    model = GLMModel.__new__(GLMModel)
    model.model = "fake"
    model.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(model.reason("context", "prompt"), timeout=0.02)
    finally:
        release.set()


def test_glm_transport_has_timeout_and_no_hidden_retries(monkeypatch):
    constructor = Mock()
    monkeypatch.setattr("models.glm_model.ZhipuAI", constructor)
    monkeypatch.setattr(config.model, "model_timeout_seconds", 7)
    GLMModel(api_key="synthetic")
    constructor.assert_called_once_with(api_key="synthetic", timeout=7, max_retries=0)


@pytest.mark.asyncio
async def test_glm_and_claude_close_owned_transports():
    glm = GLMModel.__new__(GLMModel)
    glm.client = SimpleNamespace(close=Mock())
    claude = ClaudeModel.__new__(ClaudeModel)
    claude.async_client = SimpleNamespace(close=AsyncMock())
    await glm.close()
    await claude.close()
    glm.client.close.assert_called_once()
    claude.async_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_openai_client_timeout_and_cleanup_without_optional_sdk(monkeypatch):
    client = SimpleNamespace(close=AsyncMock())
    constructor = Mock(return_value=client)
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=constructor))
    monkeypatch.setattr(config.model, "model_timeout_seconds", 9)
    path = Path(__file__).parents[1] / "models" / "openai_model.py"
    spec = importlib.util.spec_from_file_location("isolated_openai_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model = module.OpenAIModel(api_key="synthetic")
    constructor.assert_called_once_with(api_key="synthetic", timeout=9, max_retries=0)
    await model.close()
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_ollama_close_clears_session():
    model = OllamaModel()
    session = SimpleNamespace(close=AsyncMock())
    model.session = session
    await model.close()
    await model.close()
    session.close.assert_awaited_once()
    assert model.session is None


@pytest.fixture
def clean_config(monkeypatch):
    for name in (
        "MODEL_PROVIDER",
        "USE_LOCAL_MODEL",
        "FALLBACK_TO_CLAUDE",
        "CLAUDE_API_KEY",
        "OPENAI_API_KEY",
        "ZHIPUAI_API_KEY",
        "GLM_API_KEY",
        "AUTO_CHECKBOXES",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FALLBACK_TO_CLAUDE", "false")
    monkeypatch.setattr(Config, "_create_directories", lambda self: None)


def test_legacy_provider_flag_is_honored(clean_config, monkeypatch):
    monkeypatch.setenv("USE_LOCAL_MODEL", "false")
    assert Config().model.model_provider == "claude"
    monkeypatch.setenv("MODEL_PROVIDER", "OPENAI")
    assert Config().model.model_provider == "openai"


def test_checkboxes_are_opt_in(clean_config):
    assert Config().agent.auto_checkboxes is False


def test_claude_fallback_is_opt_in(clean_config, monkeypatch):
    monkeypatch.delenv("FALLBACK_TO_CLAUDE")
    settings = Config()
    assert settings.model.fallback_to_claude is False
    assert settings.validate_config()


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("unknown", "Unknown MODEL_PROVIDER"),
        ("openai", "OPENAI_API_KEY"),
        ("glm", "ZHIPUAI_API_KEY"),
        ("claude", "CLAUDE_API_KEY"),
    ],
)
def test_provider_validation_fails_early(clean_config, monkeypatch, provider, expected):
    monkeypatch.setenv("MODEL_PROVIDER", provider)
    with pytest.raises(ValueError, match=expected):
        Config().validate_config()


def test_local_only_configuration_needs_no_cloud_key(clean_config):
    assert Config().validate_config()


def test_enabled_fallback_requires_credentials(clean_config, monkeypatch):
    monkeypatch.setenv("FALLBACK_TO_CLAUDE", "true")
    with pytest.raises(ValueError, match="FALLBACK_TO_CLAUDE=false"):
        Config().validate_config()


def test_nonpositive_timeout_is_rejected(clean_config, monkeypatch):
    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", "0")
    with pytest.raises(ValueError, match="must be positive"):
        Config().validate_config()


def test_selector_validates_before_initializing(monkeypatch):
    initialize = Mock()
    monkeypatch.setattr(ModelSelector, "_initialize_models", initialize)
    monkeypatch.setattr(config, "validate_config", Mock(side_effect=ValueError("bad")))
    with pytest.raises(ValueError, match="bad"):
        ModelSelector()
    initialize.assert_not_called()


def test_missing_openai_sdk_is_actionable_and_not_silently_replaced(monkeypatch):
    monkeypatch.setitem(sys.modules, "models.openai_model", None)
    selector = selector_with(None, SimpleNamespace())
    selector.provider = "openai"
    with pytest.raises(ImportError, match=r"nlwebagent\[openai\]"):
        selector._initialize_models()


def test_missing_glm_sdk_is_actionable(monkeypatch):
    monkeypatch.setattr("models.glm_model.ZhipuAI", None)
    monkeypatch.setitem(sys.modules, "zhipuai", None)
    with pytest.raises(ImportError, match=r"nlwebagent\[glm\]"):
        GLMModel(api_key="synthetic")
