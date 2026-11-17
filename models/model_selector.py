"""Select configured providers with independent deadlines and Claude fallback."""

import asyncio
import logging
from typing import Optional, Tuple

from config import config

logger = logging.getLogger(__name__)


class ModelSelector:
    def __init__(self):
        config.validate_config()
        self.ollama = None
        self.openai = None
        self.glm = None
        self.claude = None
        self.provider = config.model.model_provider
        self.fallback_to_claude = config.model.fallback_to_claude
        self.timeout_seconds = config.model.model_timeout_seconds
        self._initialize_models()

    def _initialize_models(self):
        # Configuration/import errors are actionable, not inference failures.
        # Do not silently switch providers when a requested SDK is missing.
        getattr(self, f"_init_{self.provider}")()
        if self.fallback_to_claude and self.provider != "claude":
            self._init_claude()

    def _init_ollama(self):
        from models.ollama_model import OllamaModel

        self.ollama = OllamaModel(config.model.local_model_name)

    def _init_openai(self):
        try:
            from models.openai_model import OpenAIModel
        except ImportError as exc:
            raise ImportError(
                'OpenAI provider requires: pip install "nlwebagent[openai]"'
            ) from exc
        self.openai = OpenAIModel(model=config.model.openai_model_name)

    def _init_glm(self):
        from models.glm_model import GLMModel

        self.glm = GLMModel(model=config.model.glm_model_name)

    def _init_claude(self):
        from models.claude_model import ClaudeModel

        self.claude = ClaudeModel(base_url=config.model.claude_base_url)

    def get_primary_model(self) -> Tuple[object, str]:
        model = getattr(self, self.provider, None)
        if model is None:
            raise RuntimeError(f"Configured model {self.provider} is unavailable")
        return model, self.provider

    async def _call_with_fallback(self, method: str, *args) -> Tuple[str, str]:
        model, provider = self.get_primary_model()
        try:
            result = await asyncio.wait_for(
                getattr(model, method)(*args), timeout=self.timeout_seconds
            )
            return result, provider
        except Exception as exc:
            # Do not log provider exception bodies: they may echo task secrets.
            logger.warning("%s %s failed (%s)", provider, method, type(exc).__name__)
            if not (self.fallback_to_claude and self.claude and provider != "claude"):
                raise
        # A fallback receives its own full deadline. Cancellation from the caller
        # propagates and never starts a new request.
        result = await asyncio.wait_for(
            getattr(self.claude, method)(*args), timeout=self.timeout_seconds
        )
        return result, "claude_fallback"

    async def decide_next_action_with_fallback(
        self,
        screenshot_path: str,
        task: str,
        history: Optional[str] = None,
        error_hint: Optional[str] = None,
        dom_context: Optional[str] = None,
    ) -> Tuple[str, str]:
        return await self._call_with_fallback(
            "decide_next_action",
            screenshot_path,
            task,
            history,
            error_hint,
            dom_context,
        )

    async def analyze_screenshot_with_fallback(
        self, screenshot_path: str, prompt: str
    ) -> Tuple[str, str]:
        return await self._call_with_fallback(
            "analyze_screenshot", screenshot_path, prompt
        )

    async def close(self):
        # Close every initialized client even when another client's cleanup fails.
        models = [self.ollama, self.openai, self.glm, self.claude]
        unique = {id(model): model for model in models if model is not None}
        results = await asyncio.gather(
            *(model.close() for model in unique.values()), return_exceptions=True
        )
        for result in results:
            if isinstance(result, BaseException):
                logger.warning("Model cleanup failed (%s)", type(result).__name__)
