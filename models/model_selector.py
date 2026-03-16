"""
Model selector with support for multiple providers.

Supports:
- Ollama (local)
- OpenAI (GPT-4 Vision)
- GLM (GLM-4V)
- Claude (fallback)
"""
import logging
from typing import Optional, Tuple

from config import config

logger = logging.getLogger(__name__)


class ModelSelector:
    """Selects and manages AI model instances with fallback support."""

    def __init__(self):
        self.ollama = None
        self.openai = None
        self.glm = None
        self.claude = None

        self.provider = config.model.model_provider
        self.fallback_to_claude = config.model.fallback_to_claude

        self._initialize_models()

    def _initialize_models(self):
        """Initialize models based on configuration."""
        # Initialize primary provider
        if self.provider == "ollama":
            self._init_ollama()
        elif self.provider == "openai":
            self._init_openai()
        elif self.provider == "glm":
            self._init_glm()
        elif self.provider == "claude":
            self._init_claude()

        # Initialize Claude as fallback if enabled
        if self.fallback_to_claude and self.provider != "claude":
            self._init_claude()

    def _init_ollama(self):
        """Initialize Ollama model."""
        try:
            from models.ollama_model import OllamaModel

            self.ollama = OllamaModel(config.model.local_model_name)
            logger.info(f"Ollama initialized: {config.model.local_model_name}")
        except Exception as e:
            logger.warning(f"Ollama init failed: {e}")
            if self.provider == "ollama" and not self.fallback_to_claude:
                raise

    def _init_openai(self):
        """Initialize OpenAI model."""
        try:
            from models.openai_model import OpenAIModel

            self.openai = OpenAIModel(model=config.model.openai_model_name)
            logger.info(f"OpenAI initialized: {config.model.openai_model_name}")
        except Exception as e:
            logger.warning(f"OpenAI init failed: {e}")
            if self.provider == "openai" and not self.fallback_to_claude:
                raise

    def _init_glm(self):
        """Initialize GLM model."""
        try:
            from models.glm_model import GLMModel

            self.glm = GLMModel(model=config.model.glm_model_name)
            logger.info(f"GLM initialized: {config.model.glm_model_name}")
        except Exception as e:
            logger.warning(f"GLM init failed: {e}")
            if self.provider == "glm" and not self.fallback_to_claude:
                raise

    def _init_claude(self):
        """Initialize Claude model."""
        try:
            from models.claude_model import ClaudeModel

            self.claude = ClaudeModel(base_url=config.model.claude_base_url)
            logger.info("Claude initialized")
        except Exception as e:
            logger.warning(f"Claude init failed: {e}")

    def get_primary_model(self) -> Tuple[object, str]:
        """Get the primary model based on provider configuration."""
        if self.provider == "ollama" and self.ollama:
            return self.ollama, "ollama"
        elif self.provider == "openai" and self.openai:
            return self.openai, "openai"
        elif self.provider == "glm" and self.glm:
            return self.glm, "glm"
        elif self.provider == "claude" and self.claude:
            return self.claude, "claude"

        # Fallback chain
        if self.ollama:
            return self.ollama, "ollama_fallback"
        if self.openai:
            return self.openai, "openai_fallback"
        if self.glm:
            return self.glm, "glm_fallback"
        if self.claude:
            return self.claude, "claude_fallback"

        raise RuntimeError("No models available")

    async def decide_next_action_with_fallback(
        self,
        screenshot_path: str,
        task: str,
        history: Optional[str] = None,
        error_hint: Optional[str] = None,
        dom_context: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Decide next action using the configured model with Claude fallback.

        Returns:
            Tuple of (action_string, model_used)
        """
        # Try primary model first
        primary_model, provider = self.get_primary_model()

        try:
            action = await primary_model.decide_next_action(
                screenshot_path, task, history, error_hint, dom_context
            )
            return action, provider
        except Exception as e:
            logger.error(f"{provider} failed: {e}")

            # Fallback to Claude if enabled and not already using Claude
            if self.fallback_to_claude and self.claude and provider != "claude":
                logger.info("Falling back to Claude")
                action = await self.claude.decide_next_action(
                    screenshot_path, task, history, error_hint, dom_context
                )
                return action, "claude_fallback"

            raise RuntimeError(f"Model {provider} failed and no fallback available")

    async def close(self):
        """Close all model connections."""
        if self.ollama:
            await self.ollama.close()
