import logging
from typing import Optional

from anthropic import Anthropic, AsyncAnthropic

from models.base_model import AIModel
from config import config

logger = logging.getLogger(__name__)


class ClaudeModel(AIModel):
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        key = api_key or config.claude_api_key
        if not key:
            raise ValueError("CLAUDE_API_KEY not configured")

        # Support custom base_url for z.ai or other proxies
        client_kwargs = {"api_key": key}
        if base_url:
            client_kwargs["base_url"] = base_url

        self.client = Anthropic(**client_kwargs)
        self.async_client = AsyncAnthropic(**client_kwargs)
        self.model = config.model.claude_model_name

    async def analyze_screenshot(self, screenshot_path: str, prompt: str) -> str:
        self._ensure_image_path(screenshot_path)
        image_b64 = self._image_to_base64(screenshot_path)

        import mimetypes

        mime_type, _ = mimetypes.guess_type(screenshot_path)
        if not mime_type or not mime_type.startswith("image/"):
            mime_type = "image/png"

        message = await self.async_client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )

        return message.content[0].text

    async def reason(self, context: str, prompt: str) -> str:
        full_prompt = f"""Context: {context}

Task: {prompt}"""

        message = await self.async_client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": full_prompt}],
        )

        return message.content[0].text

    async def decide_next_action(
        self,
        screenshot_path: str,
        task: str,
        history: Optional[str] = None,
        error_hint: Optional[str] = None,
        dom_context: Optional[str] = None,
    ) -> str:
        self._ensure_image_path(screenshot_path)
        image_b64 = self._image_to_base64(screenshot_path)

        import mimetypes

        mime_type, _ = mimetypes.guess_type(screenshot_path)
        if not mime_type or not mime_type.startswith("image/"):
            mime_type = "image/png"

        history_text = f"\nPrevious: {history}" if history else ""
        error_text = (
            f"\nYour last action was invalid or failed because: {error_hint}\n"
            "Output only a valid action."
            if error_hint
            else ""
        )

        # Include DOM context if available
        dom_text = ""
        if dom_context:
            dom_text = f"\n\n{dom_context}\n"

        decision_prompt = f"""Decide the NEXT action for: {task}
{history_text}{error_text}{dom_text}
Return exactly ONE line using one of these formats:
CLICK:<css-selector>        (preferred - use selectors from DOM context above)
CLICK_AT:<x>:<y>            (fallback when no selector is obvious)
TYPE:<css-selector>:<text>  (preferred - use selectors from DOM context above)
TYPE_AT:<x>:<y>:<text>      (fallback when no selector is obvious)
EXTRACT:<css-selector>:<attr>
NAVIGATE:<url>
SCROLL:<up|down|left|right>:<pixels>
WAIT:<seconds>
DONE
ERROR:<message>

Rules:
- PREFER selector-based actions using selectors from the DOM context above.
- Use CLICK_AT/TYPE_AT only when no matching selector is found in DOM context.
- Do NOT add bullet points, explanations, or multiple lines.
- Do NOT include words like selector=, text=, url=, attr=.
- Do NOT wrap values in quotes.
- Do NOT prefix with phrases like "The next action is:".
- Use normalized coordinates (0.0–1.0) for x/y when using _AT actions.
- Do NOT repeatedly NAVIGATE to the same URL; if already on the page, use CLICK/TYPE.
- Do NOT include status text like "-> success" or invent new actions.
"""

        message = await self.async_client.messages.create(
            model=self.model,
            max_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": decision_prompt},
                    ],
                }
            ],
        )

        return message.content[0].text.strip()
