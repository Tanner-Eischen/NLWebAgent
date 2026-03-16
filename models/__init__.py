"""Model implementations for web automation agent."""

from models.base_model import AIModel
from models.ollama_model import OllamaModel
from models.claude_model import ClaudeModel
from models.model_selector import ModelSelector


# Lazy imports for optional dependencies
def get_openai_model():
    from models.openai_model import OpenAIModel

    return OpenAIModel


def get_glm_model():
    from models.glm_model import GLMModel

    return GLMModel


__all__ = [
    "AIModel",
    "OllamaModel",
    "ClaudeModel",
    "ModelSelector",
    "get_openai_model",
    "get_glm_model",
]
