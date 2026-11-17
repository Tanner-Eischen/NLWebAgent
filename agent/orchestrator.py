import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from agent.actions import (
    ActionParseError,
    ActionType,
    parse_action,
    parse_action_lenient,
)
from auth.manager import AuthManager
from auth.redaction import SecretRedactor
from browser.playwright_agent import BrowserController
from config import config
from models.model_selector import ModelSelector

logger = logging.getLogger(__name__)


class WebAutomationAgent:
    def __init__(
        self,
        session_id: str = None,
        model_selector: Optional[ModelSelector] = None,
        browser: Optional[BrowserController] = None,
        auth_manager: Optional[AuthManager] = None,
    ):
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.model_selector: Optional[ModelSelector] = model_selector
        self.browser: Optional[BrowserController] = browser
        self.auth_manager = auth_manager or AuthManager()
        self.max_retries = config.agent.max_retries
        self._last_result: Optional[Dict[str, Any]] = None
        self.redactor = getattr(self.auth_manager, "redactor", None) or SecretRedactor()
        if self.browser:
            self.browser.redactor = self.redactor
        self._closed = False

    async def initialize(self):
        logger.info("Initializing WebAutomationAgent")
        if not self.model_selector:
            self.model_selector = ModelSelector()
        if not self.browser:
            self.browser = BrowserController(self.session_id)
        self.browser.redactor = self.redactor
        await self.browser.create_session()

    async def execute_task(
        self,
        task_description: str,
        start_url: Optional[str] = None,
        max_steps: int = 20,
    ) -> Dict[str, Any]:
        if not self.model_selector or not self.browser:
            raise RuntimeError("Agent not initialized")
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        self.browser.redactor = self.redactor
        result: Dict[str, Any] = {
            "task": task_description,
            "status": "running",
            "outcome": "unverified",
            "steps_taken": 0,
            "actions": [],
            "errors": [],
            "screenshots": [],
            "extractions": [],
            "videos": [],
            "transcript": None,
        }
        self._last_result = result
        history = []
        transcript_start = len(getattr(self.browser, "transcript", []))
        try:
            if start_url:
                if not await self.browser.navigate(start_url):
                    raise RuntimeError(self.browser.last_error or "Navigation failed")
                logged_in = await self.auth_manager.ensure_logged_in(
                    self.browser, start_url
                )
                if isinstance(self.auth_manager, AuthManager):
                    if self.auth_manager.requires_login(start_url) and not logged_in:
                        raise RuntimeError("Configured authentication policy failed")

            screenshot = await self.browser.take_screenshot("step_00")
            result["screenshots"].append(screenshot)
            for step in range(max_steps):
                if (
                    config.agent.pause_on_captcha
                    and await self.browser.detect_captcha()
                ):
                    result["status"] = "paused_for_captcha"
                    result["errors"].append(
                        "CAPTCHA detected; complete it before starting another task."
                    )
                    break
                if config.agent.auto_checkboxes:
                    if await self.browser.click_first_checkbox():
                        history.append("AUTO_CHECKBOX -> success")

                last_error = None
                for attempt in range(self.max_retries + 1):
                    entry = {
                        "step": step + 1,
                        "attempt": attempt + 1,
                        "action": "",
                        "model": "",
                    }
                    try:
                        dom_context = await self.browser.get_dom_context(
                            max_elements=40
                        )
                        (
                            raw,
                            provider,
                        ) = await self.model_selector.decide_next_action_with_fallback(
                            screenshot_path=screenshot,
                            task=self.redactor.redact(task_description),
                            history=self.redactor.redact("\n".join(history[-5:])),
                            error_hint=self.redactor.redact(last_error),
                            dom_context=self.redactor.redact(dom_context),
                        )
                        entry["model"] = provider
                        try:
                            action = parse_action(raw)
                        except ActionParseError:
                            try:
                                action = parse_action_lenient(raw)
                            except ActionParseError:
                                # Parser exceptions can contain the entire model output.
                                raise ValueError(
                                    "Invalid action; return one structured JSON action or ACTION:... line"
                                ) from None
                        if action.type in {ActionType.TYPE, ActionType.TYPE_AT}:
                            if not re.fullmatch(
                                r"\$\{ENV:[A-Za-z_][A-Za-z0-9_]*\}", action.text
                            ):
                                self.redactor.add(action.text)
                        safe_action = self.redactor.redact(
                            action.model_dump(mode="json")
                        )
                        if "text" in safe_action:
                            safe_action["text"] = (
                                action.text
                                if re.fullmatch(
                                    r"\$\{ENV:[A-Za-z_][A-Za-z0-9_]*\}", action.text
                                )
                                else "[REDACTED]"
                            )
                        # Canonical JSON avoids ambiguous selectors/text in persisted histories.
                        entry["action"] = json.dumps(safe_action, ensure_ascii=False)
                        entry["parsed_action"] = safe_action
                        if action.type == ActionType.DONE:
                            entry["status"] = "success"
                            result["status"] = "success"
                        elif action.type == ActionType.ERROR:
                            entry.update(
                                status="failed",
                                error=self.redactor.redact(action.message),
                            )
                            result["actions"].append(entry)
                            result["errors"].append(entry["error"])
                            result["status"] = "failed"
                            break
                        else:
                            if (
                                action.type == ActionType.NAVIGATE
                                and self._is_redundant_navigation(action.url, history)
                            ):
                                raise ValueError(
                                    "Redundant navigation to the current URL"
                                )
                            ok, error = await self._execute_action(action, result)
                            if not ok:
                                raise RuntimeError(error or "Action failed")
                            entry["status"] = "success"
                        result["actions"].append(entry)
                        history.append(entry["action"] + " -> success")
                        break
                    except Exception as exc:
                        error = self.redactor.redact(str(exc))
                        entry.update(status="failed", error=error)
                        result["actions"].append(entry)
                        result["errors"].append(error)
                        history.append(entry["action"] + " -> failed: " + error)
                        last_error = self._augment_error_hint(
                            error, force_coordinate=self._is_selector_error(error)
                        )
                        if attempt == self.max_retries:
                            result["status"] = "failed"
                        else:
                            screenshot = await self.browser.take_screenshot(
                                f"step_{step:02d}_retry_{attempt}"
                            )
                            result["screenshots"].append(screenshot)
                if result["status"] != "running":
                    break
                if step < max_steps - 1:
                    screenshot = await self.browser.take_screenshot(
                        f"step_{step + 1:02d}"
                    )
                    result["screenshots"].append(screenshot)
            if result["status"] == "running":
                result["status"] = "max_steps_exceeded"
        except Exception as exc:
            result["status"] = "error"
            result["errors"].append(self.redactor.redact(str(exc)))
        result["steps_taken"] = len(result["actions"])
        result["executed_actions"] = getattr(self.browser, "transcript", [])[
            transcript_start:
        ]
        safe_result = self.redactor.redact(result)
        result.clear()
        result.update(safe_result)
        return result

    async def _execute_action(
        self, action: Any, result: Dict[str, Any]
    ) -> Tuple[bool, Optional[str]]:
        if action.type == ActionType.CLICK:
            ok = await self.browser.click(action.selector)
            if not ok and self._is_selector_error(self.browser.last_error):
                # Self-healing: fallback to vision-guided coordinates
                coords = await self._get_fallback_coordinates(action.selector)
                if coords:
                    ok = await self.browser.click_at(coords[0], coords[1])
                    if ok:
                        logger.info(
                            f"Self-healing: CLICK fell back to coordinates {coords}"
                        )
            return ok, self.browser.last_error

        if action.type == ActionType.CLICK_AT:
            ok = await self.browser.click_at(action.x, action.y)
            return ok, self.browser.last_error

        if action.type == ActionType.TYPE:
            ok = await self.browser.type_text(action.selector, action.text)
            if not ok and self._is_selector_error(self.browser.last_error):
                # Self-healing: fallback to vision-guided coordinates
                coords = await self._get_fallback_coordinates(action.selector)
                if coords:
                    ok = await self.browser.type_at(coords[0], coords[1], action.text)
                    if ok:
                        logger.info(
                            f"Self-healing: TYPE fell back to coordinates {coords}"
                        )
            return ok, self.browser.last_error

        if action.type == ActionType.TYPE_AT:
            ok = await self.browser.type_at(action.x, action.y, action.text)
            return ok, self.browser.last_error

        if action.type == ActionType.NAVIGATE:
            ok = await self.browser.navigate(action.url)
            await asyncio.sleep(0.5)
            return ok, self.browser.last_error

        if action.type == ActionType.SCROLL:
            ok = await self.browser.scroll(action.direction, action.amount)
            return ok, self.browser.last_error

        if action.type == ActionType.WAIT:
            ok = await self.browser.wait(action.seconds)
            return ok, self.browser.last_error

        if action.type == ActionType.EXTRACT:
            ok, value = await self.browser.extract(action.selector, action.attr)
            if ok and value is not None:
                result["extractions"].append(
                    {
                        "selector": action.selector,
                        "attr": action.attr,
                        "value": value,
                    }
                )
            return ok, self.browser.last_error

        return False, f"Unsupported action type: {action.type}"

    async def _get_fallback_coordinates(
        self, selector: str
    ) -> Optional[Tuple[float, float]]:
        """Get fallback coordinates via vision model when selector fails."""
        if not self.model_selector or not self.browser:
            return None
        try:
            # Take a fresh screenshot for vision analysis
            screenshot = await self.browser.take_screenshot("fallback_vision")
            # Ask vision model to find the element described by the selector
            prompt = f"Find the element matching selector '{selector}'. Return coordinates as x:y (normalized 0-1). If not found, return NONE."
            response, _ = await self.model_selector.analyze_screenshot_with_fallback(
                screenshot, self.redactor.redact(prompt)
            )
            if response and ":" in response and "NONE" not in response.upper():
                parts = response.strip().split(":")
                if len(parts) >= 2:
                    x = float(parts[0])
                    y = float(parts[1])
                    if 0 <= x <= 1 and 0 <= y <= 1:
                        return (x, y)
        except Exception as e:
            logger.warning("Vision fallback failed: %s", type(e).__name__)
        return None

    @staticmethod
    def _augment_error_hint(error_msg: str, force_coordinate: bool = False) -> str:
        if not error_msg:
            return error_msg
        lowered = error_msg.lower()
        if "selector not found" in lowered or "unknown engine" in lowered:
            if force_coordinate:
                return f"{error_msg}. Output ONLY CLICK_AT:x:y or TYPE_AT:x:y:text."
            return (
                f"{error_msg}. Use CLICK_AT:x:y or TYPE_AT:x:y:text if selectors fail."
            )
        return error_msg

    @staticmethod
    def _is_selector_error(error_msg: Optional[str]) -> bool:
        if not error_msg:
            return False
        lowered = error_msg.lower()
        return "selector not found" in lowered or "unknown engine" in lowered

    def _is_redundant_navigation(self, url: str, action_history: list) -> bool:
        if not self.browser or not self.browser.page or not url:
            return False
        current = (self.browser.page.url or "").rstrip("/")
        target = url.rstrip("/")
        if current and current == target:
            return True
        # Avoid looping NAVIGATE to same target repeatedly
        recent = action_history[-2:] if action_history else []
        for entry in recent:
            if entry.startswith("NAVIGATE:") and target in entry:
                return True
        return False

    async def close(self) -> Dict[str, Any]:
        if self._closed:
            return self._last_result or {}
        self._closed = True
        artifacts: Dict[str, Any] = {}
        try:
            if self.browser:
                artifacts = await self.browser.close()
        finally:
            if self.model_selector:
                await self.model_selector.close()
        if self._last_result is not None:
            self._last_result.update(self.redactor.redact(artifacts))
            return self._last_result
        return self.redactor.redact(artifacts)
