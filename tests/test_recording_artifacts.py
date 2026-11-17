import unittest
from pathlib import Path

import pytest

from agent.orchestrator import WebAutomationAgent
from browser.playwright_agent import BrowserController

pytestmark = pytest.mark.browser


class FakeModelSelector:
    def __init__(self, actions):
        self.actions = list(actions)

    async def decide_next_action_with_fallback(
        self, screenshot_path, task, history=None, error_hint=None, dom_context=None
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
        browser = BrowserController("recording_artifacts", record_video=True)
        agent = WebAutomationAgent(
            "recording_artifacts", model_selector=model, browser=browser
        )

        await agent.initialize()
        result = await agent.execute_task(
            task_description="Wait briefly and finish",
            start_url=start_url,
            max_steps=2,
        )
        result = await agent.close()

        self.assertEqual(result["status"], "success", result["errors"])
        self.assertEqual(result["steps_taken"], 2)
        self.assertTrue(result["screenshots"])
        self.assertTrue(result["videos"])
        for video in result["videos"]:
            self.assertTrue(Path(video).exists())


if __name__ == "__main__":
    unittest.main()
