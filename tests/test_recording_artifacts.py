import os
import unittest
from pathlib import Path

os.environ.setdefault("HEADLESS", "true")
os.environ.setdefault("RECORD_VIDEO", "true")
os.environ.setdefault("TIMEOUT_SECONDS", "2")

try:
    import playwright.async_api  # noqa: F401
except Exception as exc:
    raise unittest.SkipTest(f"playwright not installed: {exc}")

from config import config

config.reload()

from agent.orchestrator import WebAutomationAgent
from browser.playwright_agent import BrowserController


class FakeModelSelector:
    def __init__(self, actions):
        self.actions = list(actions)

    async def decide_next_action_with_fallback(
        self, screenshot_path, task, history=None, error_hint=None
    ):
        if self.actions:
            return self.actions.pop(0), "fake"
        return "DONE", "fake"

    async def close(self):
        return None


class RecordingArtifactsTests(unittest.IsolatedAsyncioTestCase):
    async def test_video_and_screenshots_recorded(self):
        fixture_path = Path(__file__).parent / "fixtures" / "retry.html"
        start_url = fixture_path.resolve().as_uri()

        model = FakeModelSelector(["WAIT:0.2", "DONE"])
        browser = BrowserController("recording_artifacts")
        agent = WebAutomationAgent("recording_artifacts", model_selector=model, browser=browser)

        await agent.initialize()
        result = await agent.execute_task(
            task_description="Wait briefly and finish",
            start_url=start_url,
            max_steps=2,
        )
        result = await agent.close()

        self.assertTrue(result["screenshots"])
        self.assertTrue(result["videos"])
        for video in result["videos"]:
            self.assertTrue(Path(video).exists())


if __name__ == "__main__":
    unittest.main()
