import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass
class ModelConfig:
    use_local_model: bool = True
    fallback_to_claude: bool = True
    # Model provider: "ollama", "openai", "glm", "claude"
    model_provider: str = "ollama"
    local_model_name: str = "llama3.2-vision:11b"
    claude_model_name: str = "claude-3-5-haiku-20241022"  # Use glm-5 via z.ai
    openai_model_name: str = "gpt-4o"
    glm_model_name: str = "glm-4v-flash"
    ollama_host: str = "http://localhost:11434"
    claude_base_url: Optional[str] = None  # For z.ai proxy
    vision_confidence_threshold: float = 0.7
    model_timeout_seconds: int = 60
    model_num_predict: int = 128


@dataclass
class BrowserConfig:
    headless: bool = False
    record_video: bool = True
    screenshot_dir: str = "./recordings/screenshots"
    video_dir: str = "./recordings/videos"
    transcript_dir: str = "./recordings/transcripts"
    timeout_seconds: int = 30
    viewport_width: int = 1280
    viewport_height: int = 720
    wait_until: str = "domcontentloaded"
    reuse_storage_state: bool = True
    storage_state_path: str = "./recordings/storage_state.json"


@dataclass
class AgentConfig:
    max_retries: int = 3
    verbose: bool = True
    enable_logging: bool = True
    log_level: str = "INFO"
    auto_checkboxes: bool = True
    pause_on_captcha: bool = True
    action_strategy: str = "selector_first"  # "selector_first" or "coordinate_only"


@dataclass
class AuthConfig:
    enable_login_policies: bool = True


class Config:
    def __init__(self):
        self.model = ModelConfig(
            use_local_model=self._get_bool("USE_LOCAL_MODEL", True),
            fallback_to_claude=self._get_bool("FALLBACK_TO_CLAUDE", True),
            model_provider=os.getenv("MODEL_PROVIDER", "ollama"),
            local_model_name=os.getenv("OLLAMA_MODEL", "llama3.2-vision:11b"),
            claude_model_name=os.getenv("CLAUDE_MODEL", "claude-3-5-haiku-20241022"),
            openai_model_name=os.getenv("OPENAI_MODEL", "gpt-4o"),
            glm_model_name=os.getenv("GLM_MODEL", "glm-4v-flash"),
            ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            claude_base_url=os.getenv("CLAUDE_BASE_URL"),
            vision_confidence_threshold=float(
                os.getenv("VISION_CONFIDENCE_THRESHOLD", "0.7")
            ),
            model_timeout_seconds=int(os.getenv("MODEL_TIMEOUT_SECONDS", "60")),
            model_num_predict=int(os.getenv("MODEL_NUM_PREDICT", "128")),
        )

        self.browser = BrowserConfig(
            headless=self._get_bool("HEADLESS", False),
            record_video=self._get_bool("RECORD_VIDEO", True),
            screenshot_dir=os.getenv("SCREENSHOT_DIR", "./recordings/screenshots"),
            video_dir=os.getenv("VIDEO_DIR", "./recordings/videos"),
            transcript_dir=os.getenv("TRANSCRIPT_DIR", "./recordings/transcripts"),
            timeout_seconds=int(os.getenv("TIMEOUT_SECONDS", "30")),
            wait_until=os.getenv("NAVIGATION_WAIT_UNTIL", "domcontentloaded"),
            reuse_storage_state=self._get_bool("REUSE_STORAGE_STATE", True),
            storage_state_path=os.getenv(
                "STORAGE_STATE_PATH", "./recordings/storage_state.json"
            ),
        )

        self.agent = AgentConfig(
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            verbose=self._get_bool("VERBOSE", True),
            enable_logging=self._get_bool("ENABLE_LOGGING", True),
            auto_checkboxes=self._get_bool("AUTO_CHECKBOXES", True),
            pause_on_captcha=self._get_bool("PAUSE_ON_CAPTCHA", True),
            action_strategy=os.getenv("ACTION_STRATEGY", "selector_first"),
        )

        self.auth = AuthConfig(
            enable_login_policies=self._get_bool("ENABLE_LOGIN_POLICIES", True)
        )

        self.claude_api_key = os.getenv("CLAUDE_API_KEY")
        self._create_directories()

    @staticmethod
    def _get_bool(key: str, default: bool = False) -> bool:
        value = os.getenv(key, str(default)).lower()
        return value in ("true", "1", "yes", "on")

    def _create_directories(self):
        for directory in [
            self.browser.screenshot_dir,
            self.browser.video_dir,
            self.browser.transcript_dir,
        ]:
            os.makedirs(directory, exist_ok=True)

        storage_dir = Path(self.browser.storage_state_path).parent
        os.makedirs(storage_dir, exist_ok=True)

    def get_credential(self, service: str, key: str) -> Optional[str]:
        env_key = f"{service.upper()}_{key.upper()}"
        value = os.getenv(env_key)
        if not value:
            raise ValueError(f"Missing credential: {service}.{key}")
        return value

    def validate_config(self) -> bool:
        if self.model.fallback_to_claude and not self.claude_api_key:
            raise ValueError(
                "Claude fallback enabled but CLAUDE_API_KEY not set in .env"
            )

        if self.browser.wait_until not in {"load", "domcontentloaded", "networkidle"}:
            raise ValueError(
                "NAVIGATION_WAIT_UNTIL must be one of: load, domcontentloaded, networkidle"
            )

        return True

    def reload(self):
        self.__init__()


config = Config()
