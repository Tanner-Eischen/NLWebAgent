import os
import unittest
from pathlib import Path

os.environ.setdefault("HEADLESS", "true")
os.environ.setdefault("RECORD_VIDEO", "false")
os.environ.setdefault("TIMEOUT_SECONDS", "2")

try:
    import playwright.async_api  # noqa: F401
except Exception as exc:
    raise unittest.SkipTest(f"playwright not installed: {exc}")

from config import config  # noqa: E402

config.reload()

from agent.orchestrator import WebAutomationAgent  # noqa: E402
from browser.playwright_agent import BrowserController  # noqa: E402


class FakeModelSelector:
    def __init__(self, actions):
        self.actions = list(actions)
        self.calls = []

    async def decide_next_action_with_fallback(
        self, screenshot_path, task, history=None, error_hint=None, dom_context=None
    ):
        self.calls.append({"history": history, "error_hint": error_hint})
        if self.actions:
            return self.actions.pop(0), "fake"
        return "DONE", "fake"

    async def close(self):
        return None


class RetryBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_on_failed_action(self):
        fixture_path = Path(__file__).parent / "fixtures" / "retry.html"
        start_url = fixture_path.resolve().as_uri()

        model = FakeModelSelector(["CLICK:#missing", "DONE"])
        browser = BrowserController("retry_behavior")
        agent = WebAutomationAgent(
            "retry_behavior", model_selector=model, browser=browser
        )

        await agent.initialize()
        result = await agent.execute_task(
            task_description="Click a missing selector, then finish",
            start_url=start_url,
            max_steps=2,
        )
        result = await agent.close()

        self.assertGreaterEqual(len(model.calls), 2)
        self.assertTrue(any(a["status"] == "failed" for a in result["actions"]))
        self.assertTrue(result["errors"])
        self.assertEqual(result["status"], "success")


if __name__ == "__main__":
    unittest.main()
