import aiohttp
import asyncio
import logging
from typing import Optional

from models.base_model import AIModel
from config import config

logger = logging.getLogger(__name__)


class OllamaModel(AIModel):
    def __init__(self, model_name: str = "llama3.2-vision:11b"):
        self.model_name = model_name
        self.base_url = config.model.ollama_host
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return self.session

    async def close(self):
        if self.session:
            await self.session.close()

    async def _call_ollama(
        self,
        prompt: str,
        image_base64: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        session = await self._get_session()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        user_message = {"role": "user", "content": prompt}
        if image_base64:
            user_message["images"] = [image_base64]

        messages.append(user_message)

        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "temperature": 0.2,
            "options": {
                "num_predict": config.model.model_num_predict,
                "stop": ["\n", " OR "],
            },
        }

        try:
            async with session.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=300),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("message", {}).get("content", "").strip()
                error = await resp.text()
                logger.error(f"Ollama API error {resp.status}: {error}")
                raise RuntimeError(f"Ollama error: {resp.status}")
        except asyncio.TimeoutError:
            raise RuntimeError("Ollama request timed out")

    async def analyze_screenshot(self, screenshot_path: str, prompt: str) -> str:
        self._ensure_image_path(screenshot_path)
        image_b64 = self._image_to_base64(screenshot_path)

        analysis_prompt = f"""You are a web automation agent. Analyze this screenshot and answer:

{prompt}

Respond concisely."""

        return await self._call_ollama(
            prompt=analysis_prompt,
            image_base64=image_b64,
        )

    async def reason(self, context: str, prompt: str) -> str:
        full_prompt = f"""Context: {context}

Task: {prompt}

Respond concisely."""

        return await self._call_ollama(prompt=full_prompt)

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

        decision_prompt = f"""Decide the NEXT action for task: {task}
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
- Do NOT output multiple options or the word "OR".
"""

        return await self._call_ollama(
            prompt=decision_prompt,
            image_base64=image_b64,
        )
