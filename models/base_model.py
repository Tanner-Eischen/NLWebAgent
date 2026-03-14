from abc import ABC, abstractmethod
from pathlib import Path
import base64


class AIModel(ABC):
    @abstractmethod
    async def analyze_screenshot(self, screenshot_path: str, prompt: str) -> str:
        pass

    @abstractmethod
    async def reason(self, context: str, prompt: str) -> str:
        pass

    @staticmethod
    def _image_to_base64(image_path: str) -> str:
        with open(image_path, "rb") as image_file:
            return base64.standard_b64encode(image_file.read()).decode("utf-8")

    @staticmethod
    def _ensure_image_path(image_path: str) -> Path:
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            raise ValueError(f"Unsupported image format: {path.suffix}")
        return path