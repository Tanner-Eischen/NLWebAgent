"""Browser-free diagnostics confirming current bugs, not desired future behavior.

Uses synthetic credentials, fake model clients, and temporary empty storage state.
No browser launches, provider requests, or real credential reads are performed.
Run from any directory with the repository's installed virtual environment.
"""

import asyncio
import importlib.util
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from auth.manager import AuthManager  # noqa: E402
from auth.policies import LoginPolicy  # noqa: E402
from config import config  # noqa: E402
from models.glm_model import GLMModel  # noqa: E402
from models.model_selector import ModelSelector  # noqa: E402


async def main():
    print("CURRENT-BUG DIAGNOSTICS: observations, not future regression expectations")
    print(
        "SDK availability:",
        {
            name: importlib.util.find_spec(name) is not None
            for name in ("openai", "zhipuai")
        },
    )

    policy = LoginPolicy(
        domain="example.com",
        service="TEST",
        username_selector="#u",
        password_selector="#p",
        submit_selector="#s",
        login_url="https://example.com/login",
    )
    manager = AuthManager({"example.com": policy})
    with tempfile.TemporaryDirectory() as directory:
        state = Path(directory) / "state.json"
        state.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
        browser = SimpleNamespace(
            navigate=AsyncMock(), type_text=AsyncMock(), click=AsyncMock()
        )
        with (
            patch.object(config.auth, "enable_login_policies", True),
            patch.object(config.browser, "reuse_storage_state", True),
            patch.object(config.browser, "storage_state_path", str(state)),
        ):
            result = await manager.ensure_logged_in(
                browser, "https://example.com/protected"
            )
        print(
            "Empty storage state:",
            f"login_result={result}",
            f"navigate_calls={browser.navigate.await_count}",
            f"type_calls={browser.type_text.await_count}",
        )

    browser = SimpleNamespace(
        navigate=AsyncMock(return_value=False),
        type_text=AsyncMock(return_value=True),
        click=AsyncMock(return_value=True),
    )
    with (
        patch.object(config.auth, "enable_login_policies", True),
        patch.object(config.browser, "reuse_storage_state", False),
        patch.object(config, "get_credential", return_value="synthetic-secret"),
    ):
        result = await manager.ensure_logged_in(
            browser, "https://example.com/protected"
        )
    print(
        "Failed login navigation:",
        f"login_result={result}",
        f"type_calls={browser.type_text.await_count}",
        f"submit_calls={browser.click.await_count}",
    )

    with (
        patch.object(config.model, "use_local_model", False),
        patch.object(config.model, "model_provider", "ollama"),
        patch.object(config.model, "fallback_to_claude", False),
        patch.object(ModelSelector, "_init_ollama") as initialize,
    ):
        ModelSelector()
        print("USE_LOCAL_MODEL=false:", f"ollama_init_calls={initialize.call_count}")

    selector = object.__new__(ModelSelector)
    selector.provider = "ollama"
    selector.fallback_to_claude = True

    async def slow_provider(*args):
        await asyncio.sleep(1)
        return "DONE"

    selector.ollama = SimpleNamespace(decide_next_action=slow_provider)
    selector.openai = None
    selector.glm = None
    selector.claude = SimpleNamespace(decide_next_action=AsyncMock(return_value="DONE"))
    timed_out = False
    try:
        await asyncio.wait_for(
            selector.decide_next_action_with_fallback("unused", "synthetic task"),
            timeout=0.01,
        )
    except asyncio.TimeoutError:
        timed_out = True
    print(
        "Primary timeout:",
        f"timed_out={timed_out}",
        f"fallback_calls={selector.claude.decide_next_action.await_count}",
    )

    model = object.__new__(GLMModel)
    model.model = "fake"

    def create(**kwargs):
        time.sleep(0.1)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="DONE"))]
        )

    model.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    started = time.monotonic()
    timed_out = False
    try:
        await asyncio.wait_for(model.reason("context", "prompt"), timeout=0.01)
    except asyncio.TimeoutError:
        timed_out = True
    print(
        "Synchronous GLM client:",
        "timeout_seconds=0.01",
        f"elapsed_seconds={time.monotonic() - started:.3f}",
        f"timed_out={timed_out}",
    )


if __name__ == "__main__":
    asyncio.run(main())
