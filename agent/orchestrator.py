import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

from agent.actions import (
    ActionParseError,
    ActionType,
    parse_action,
    parse_action_lenient,
)
from auth.manager import AuthManager
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
        self._navigation_count = 0
        self._last_success_signature: Optional[str] = None
        self._repeat_success_count = 0

    async def initialize(self):
        logger.info("Initializing WebAutomationAgent")
        if not self.model_selector:
            self.model_selector = ModelSelector()
        if not self.browser:
            self.browser = BrowserController(self.session_id)
        await self.browser.create_session()

    async def execute_task(
        self,
        task_description: str,
        start_url: Optional[str] = None,
        max_steps: int = 20,
    ) -> Dict[str, Any]:
        if not self.model_selector or not self.browser:
            raise RuntimeError("Agent not initialized")

        logger.info(f"Task: {task_description}")

        result: Dict[str, Any] = {
            "task": task_description,
            "status": "running",
            "steps_taken": 0,
            "actions": [],
            "errors": [],
            "screenshots": [],
            "extractions": [],
            "videos": [],
            "transcript": None,
        }
        self._last_result = result

        try:
            if start_url:
                ok = await self.browser.navigate(start_url)
                if not ok:
                    error_msg = self.browser.last_error or "Navigation failed"
                    result["errors"].append(error_msg)
                    result["status"] = "failed"
                    return result

                self._navigation_count = 1
                await asyncio.sleep(0.5)
                await self.auth_manager.ensure_logged_in(self.browser, start_url)

            current_screenshot = await self.browser.take_screenshot("step_00")
            result["screenshots"].append(current_screenshot)

            action_history = []

            for step in range(max_steps):
                retries = 0
                last_error: Optional[str] = None
                forced_coordinate = False

                if config.agent.auto_checkboxes:
                    if (
                        config.agent.pause_on_captcha
                        and await self.browser.detect_captcha()
                    ):
                        captcha_msg = "CAPTCHA detected; waiting for manual completion."
                        result["errors"].append(captcha_msg)
                        result["status"] = "paused_for_captcha"
                        result["screenshots"].append(
                            await self.browser.take_screenshot("captcha")
                        )
                        break

                    checked = await self.browser.click_first_checkbox()
                    if checked:
                        action_history.append("AUTO_CHECKBOX -> success")

                while retries <= self.max_retries + (1 if forced_coordinate else 0):
                    history_text = (
                        "\n".join(action_history[-5:]) if action_history else ""
                    )
                    if last_error and "invalid action" in last_error.lower():
                        history_text = ""

                    # Get DOM context for better selector decisions
                    dom_context = ""
                    try:
                        dom_context = await self.browser.get_dom_context(
                            max_elements=40
                        )
                    except Exception as e:
                        logger.warning(f"Could not get DOM context: {e}")

                    logger.info("Requesting model action")
                    try:
                        action_raw, model_used = await asyncio.wait_for(
                            self.model_selector.decide_next_action_with_fallback(
                                screenshot_path=current_screenshot,
                                task=task_description,
                                history=history_text,
                                error_hint=last_error,
                                dom_context=dom_context,
                            ),
                            timeout=config.model.model_timeout_seconds,
                        )
                    except asyncio.TimeoutError:
                        error_msg = "Model timed out while deciding next action"
                        logger.error(error_msg)
                        action_entry = {
                            "step": step + 1,
                            "attempt": retries + 1,
                            "action": "",
                            "model": "timeout",
                            "status": "failed",
                            "error": error_msg,
                        }
                        result["actions"].append(action_entry)
                        result["errors"].append(error_msg)
                        retries += 1
                        last_error = error_msg
                        if retries > self.max_retries:
                            result["status"] = "failed"
                        continue

                    action_raw = action_raw.strip()
                    logger.info(f"Model output ({model_used}): {action_raw}")
                    action_entry = {
                        "step": step + 1,
                        "attempt": retries + 1,
                        "action": action_raw,
                        "model": model_used,
                    }

                    try:
                        action = parse_action(action_raw)
                    except ActionParseError as e:
                        error_msg = f"Invalid action: {e}"
                        logger.warning(error_msg)
                        try:
                            action = parse_action_lenient(action_raw)
                            logger.warning("Lenient parse used to recover action")
                        except ActionParseError:
                            error_msg = (
                                f"{error_msg}. Reply with exactly ONE line in the "
                                "format ACTION:... (no markdown, no prefixes)."
                            )
                            action_entry.update(
                                {"status": "invalid", "error": error_msg}
                            )
                            result["actions"].append(action_entry)
                            result["errors"].append(error_msg)
                            retries += 1
                            last_error = error_msg
                            if retries > self.max_retries:
                                result["status"] = "failed"
                            continue

                    if self._should_auto_type(task_description, action_history, action):
                        auto_text = self._extract_query(task_description)
                        if auto_text:
                            action_entry.update(
                                {
                                    "status": "success",
                                    "note": "Auto-typing after click",
                                }
                            )
                            result["actions"].append(action_entry)
                            submitted = await self._auto_type_last_click(
                                auto_text, result
                            )
                            action_history.append(
                                f"TYPE_AT:{auto_text} (auto after click)"
                            )
                            if submitted:
                                result["status"] = "success"
                                break
                            continue

                    if action.type == ActionType.NAVIGATE:
                        if self._navigation_count >= 1:
                            error_msg = "NAVIGATE disabled after initial load; use CLICK_AT/TYPE_AT."
                            action_entry.update(
                                {"status": "invalid", "error": error_msg}
                            )
                            result["actions"].append(action_entry)
                            result["errors"].append(error_msg)
                            retries += 1
                            last_error = error_msg
                            if retries > self.max_retries:
                                result["status"] = "failed"
                            continue
                        if self._is_redundant_navigation(action.url, action_history):
                            error_msg = (
                                "Redundant NAVIGATE to the current page; "
                                "use CLICK_AT/TYPE_AT instead."
                            )
                            action_entry.update(
                                {"status": "invalid", "error": error_msg}
                            )
                            result["actions"].append(action_entry)
                            result["errors"].append(error_msg)
                            retries += 1
                            last_error = error_msg
                            if retries > self.max_retries:
                                result["status"] = "failed"
                            continue

                    if action.type == ActionType.DONE:
                        action_entry.update({"status": "success"})
                        result["actions"].append(action_entry)
                        result["status"] = "success"
                        break

                    if action.type == ActionType.ERROR:
                        action_entry.update(
                            {"status": "failed", "error": action.message}
                        )
                        result["actions"].append(action_entry)
                        result["errors"].append(action.message)
                        result["status"] = "failed"
                        break

                    success, error_msg = await self._execute_action(action, result)
                    if not success:
                        error_msg = error_msg or "Action failed"
                        selector_error = self._is_selector_error(error_msg)
                        hint = self._augment_error_hint(
                            error_msg, force_coordinate=selector_error
                        )
                        action_entry.update({"status": "failed", "error": error_msg})
                        result["actions"].append(action_entry)
                        result["errors"].append(error_msg)
                        action_history.append(f"{action_raw} -> failed: {error_msg}")

                        failure_screenshot = await self.browser.take_screenshot(
                            f"step_{step:02d}_failure"
                        )
                        result["screenshots"].append(failure_screenshot)
                        current_screenshot = failure_screenshot

                        retries += 1
                        last_error = hint
                        if selector_error and not forced_coordinate:
                            forced_coordinate = True
                        max_attempts = self.max_retries + (
                            1 if forced_coordinate else 0
                        )
                        if retries > max_attempts:
                            result["status"] = "failed"
                        continue

                    action_entry.update({"status": "success"})
                    result["actions"].append(action_entry)
                    action_history.append(f"{action_raw} -> success")
                    signature = self._action_signature(action)
                    if signature and signature == self._last_success_signature:
                        self._repeat_success_count += 1
                    else:
                        self._repeat_success_count = 0
                        self._last_success_signature = signature
                    last_error = None
                    if self._repeat_success_count >= 1:
                        error_msg = "Repeated identical action after success; choose a different action."
                        result["errors"].append(error_msg)
                        last_error = error_msg
                    if action.type == ActionType.NAVIGATE:
                        self._navigation_count += 1
                    break

                if result["status"] in {"success", "failed", "error"}:
                    break

                if result["status"] == "running" and step < max_steps - 1:
                    current_screenshot = await self.browser.take_screenshot(
                        f"step_{step + 1:02d}"
                    )
                    result["screenshots"].append(current_screenshot)

                await asyncio.sleep(0.2)

            if result["status"] == "running":
                result["status"] = "max_steps_exceeded"

            result["steps_taken"] = len(result["actions"])

        except Exception as e:
            logger.error(f"Task failed: {e}")
            result["status"] = "error"
            result["errors"].append(str(e))

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
            response = await self.model_selector.model.analyze_screenshot(
                screenshot, prompt
            )
            if response and ":" in response and "NONE" not in response.upper():
                parts = response.strip().split(":")
                if len(parts) >= 2:
                    x = float(parts[0])
                    y = float(parts[1])
                    if 0 <= x <= 1 and 0 <= y <= 1:
                        return (x, y)
        except Exception as e:
            logger.warning(f"Vision fallback failed: {e}")
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

    @staticmethod
    def _extract_query(task_description: str) -> Optional[str]:
        if not task_description:
            return None
        if "'" in task_description:
            parts = task_description.split("'")
            if len(parts) >= 3:
                return parts[1].strip()
        if '"' in task_description:
            parts = task_description.split('"')
            if len(parts) >= 3:
                return parts[1].strip()
        return None

    def _should_auto_type(
        self, task_description: str, action_history: list, action: Any
    ) -> bool:
        if action.type != ActionType.CLICK_AT:
            return False
        if not self._extract_query(task_description):
            return False
        if action_history and "TYPE_AT" in action_history[-1]:
            return False
        return True

    async def _auto_type_last_click(self, text: str, result: Dict[str, Any]) -> bool:
        last = self._last_success_signature or ""
        if not last.startswith("CLICK_AT:"):
            return False
        try:
            _, x_str, y_str = last.split(":")
            x = float(x_str)
            y = float(y_str)
        except Exception:
            return False
        ok = await self.browser.type_at(x, y, text)
        if ok:
            result["actions"].append(
                {
                    "step": result.get("steps_taken", 0) + 1,
                    "attempt": 0,
                    "action": f"TYPE_AT:{x}:{y}:{text}",
                    "model": "auto",
                    "status": "success",
                }
            )
            pressed = await self.browser.press_enter()
            if pressed:
                result["actions"].append(
                    {
                        "step": result.get("steps_taken", 0) + 1,
                        "attempt": 0,
                        "action": "PRESS_ENTER",
                        "model": "auto",
                        "status": "success",
                    }
                )
            await asyncio.sleep(0.5)
            url = (self.browser.page.url or "").lower()
            if "search" in url or "q=" in url:
                return True
        return False

    @staticmethod
    def _action_signature(action: Any) -> Optional[str]:
        if action.type == ActionType.CLICK_AT:
            return f"CLICK_AT:{action.x:.4f}:{action.y:.4f}"
        if action.type == ActionType.TYPE_AT:
            return f"TYPE_AT:{action.x:.4f}:{action.y:.4f}:{action.text}"
        if action.type == ActionType.WAIT:
            return f"WAIT:{action.seconds}"
        if action.type == ActionType.SCROLL:
            return f"SCROLL:{action.direction}:{action.amount}"
        if action.type == ActionType.NAVIGATE:
            return f"NAVIGATE:{action.url}"
        if action.type == ActionType.DONE:
            return "DONE"
        if action.type == ActionType.ERROR:
            return f"ERROR:{action.message}"
        return None

    async def close(self) -> Dict[str, Any]:
        artifacts: Dict[str, Any] = {}

        if self.browser:
            artifacts = await self.browser.close()

        if self.model_selector:
            await self.model_selector.close()

        if self._last_result is not None:
            self._last_result.update(artifacts)
            return self._last_result

        return artifacts
