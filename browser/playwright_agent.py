import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from playwright.async_api import async_playwright

from auth.redaction import SecretRedactor, resolve_secret_references
from config import config

logger = logging.getLogger(__name__)


class BrowserController:
    def __init__(
        self,
        session_id: str = None,
        *,
        headless: Optional[bool] = None,
        record_video: Optional[bool] = None,
    ):
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.headless = config.browser.headless if headless is None else headless
        self.record_video = (
            config.browser.record_video if record_video is None else record_video
        )
        self.redactor = SecretRedactor()
        self.browser = None
        self.context = None
        self.page = None
        self.transcript: List[Dict[str, Any]] = []
        self.playwright = None
        self.last_error: Optional[str] = None
        self.video_paths: List[str] = []
        self.screenshot_paths: List[str] = []

    def _record(self, event: Dict[str, Any]) -> None:
        self.transcript.append(self.redactor.redact(event))

    def _prepare_text(self, text: str) -> Tuple[str, str]:
        resolved = resolve_secret_references(text, self.redactor)
        safe_text = self.redactor.redact(resolved)
        if re.fullmatch(r"\$\{ENV:[A-Za-z_][A-Za-z0-9_]*\}", safe_text):
            return resolved, safe_text
        # Even a mixture of literals and secret references may contain private
        # text outside the reference. Only full-value references are replayable.
        self.redactor.add(resolved)
        return resolved, "[REDACTED]"

    def _viewport(self) -> Dict[str, int]:
        return self.page.viewport_size or {
            "width": config.browser.viewport_width,
            "height": config.browser.viewport_height,
        }

    async def launch(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        logger.info("Browser launched")

    async def create_session(self):
        if not self.browser:
            await self.launch()

        context_args = {
            "viewport": {
                "width": config.browser.viewport_width,
                "height": config.browser.viewport_height,
            }
        }

        if self.record_video:
            context_args["record_video_dir"] = str(Path(config.browser.video_dir))

        storage_state_path = Path(config.browser.storage_state_path)
        if config.browser.reuse_storage_state and storage_state_path.exists():
            context_args["storage_state"] = str(storage_state_path)

        self.context = await self.browser.new_context(**context_args)
        self.page = await self.context.new_page()
        self.page.set_default_timeout(config.browser.timeout_seconds * 1000)
        self.page.set_default_navigation_timeout(config.browser.timeout_seconds * 1000)

    async def navigate(self, url: str, wait_for_selector: Optional[str] = None) -> bool:
        try:
            await self.page.goto(
                url,
                wait_until=config.browser.wait_until,
                timeout=config.browser.timeout_seconds * 1000,
            )
            if wait_for_selector:
                await self.page.wait_for_selector(
                    wait_for_selector,
                    timeout=config.browser.timeout_seconds * 1000,
                )
            logger.info("Navigation completed")
            self._record({"action": "navigate", "url": url})
            self.last_error = None
            return True
        except Exception as e:
            self.last_error = self.redactor.redact(str(e))
            logger.error("Navigation failed: %s", type(e).__name__)
            return False

    async def click(self, selector: str) -> bool:
        try:
            resolved = await self._resolve_selector(selector)
            if not resolved:
                self.last_error = self.redactor.redact(
                    f"Selector not found: {selector}"
                )
                logger.error(self.last_error)
                return False
            await self.page.click(resolved)
            logger.info("Clicked: %s", self.redactor.redact(resolved))
            self._record({"action": "click", "selector": resolved})
            self.last_error = None
            return True
        except Exception as e:
            self.last_error = self.redactor.redact(str(e))
            logger.error("Click failed: %s", type(e).__name__)
            return False

    async def type_text(self, selector: str, text: str) -> bool:
        try:
            text, safe_text = self._prepare_text(text)
            resolved = await self._resolve_selector(selector)
            if not resolved:
                self.last_error = self.redactor.redact(
                    f"Selector not found: {selector}"
                )
                logger.error(self.last_error)
                return False
            await self.page.fill(resolved, "")
            await self.page.type(resolved, text, delay=50)
            logger.info("Typed into: %s", self.redactor.redact(resolved))
            self._record({"action": "type", "selector": resolved, "text": safe_text})
            self.last_error = None
            return True
        except Exception as e:
            self.last_error = self.redactor.redact(str(e))
            logger.error("Type failed: %s", type(e).__name__)
            return False

    async def click_at(self, x: float, y: float) -> bool:
        try:
            x_px, y_px = self._resolve_coordinates(x, y)
            await self.page.mouse.click(x_px, y_px)
            logger.info(f"Clicked at: {x_px},{y_px}")
            self._record(
                {
                    "action": "click_at",
                    "x": x_px,
                    "y": y_px,
                    "coordinate_space": "pixels",
                    "viewport": self._viewport(),
                }
            )
            self.last_error = None
            return True
        except Exception as e:
            self.last_error = self.redactor.redact(str(e))
            logger.error("Click-at failed: %s", type(e).__name__)
            return False

    async def type_at(self, x: float, y: float, text: str) -> bool:
        try:
            text, safe_text = self._prepare_text(text)
            x_px, y_px = self._resolve_coordinates(x, y)
            await self.page.mouse.click(x_px, y_px)
            await self.page.keyboard.type(text, delay=50)
            logger.info(f"Typed at: {x_px},{y_px}")
            self._record(
                {
                    "action": "type_at",
                    "x": x_px,
                    "y": y_px,
                    "text": safe_text,
                    "coordinate_space": "pixels",
                    "viewport": self._viewport(),
                }
            )
            self.last_error = None
            return True
        except Exception as e:
            self.last_error = self.redactor.redact(str(e))
            logger.error("Type-at failed: %s", type(e).__name__)
            return False

    async def press_enter(self) -> bool:
        try:
            await self.page.keyboard.press("Enter")
            logger.info("Pressed Enter")
            self._record({"action": "press_enter"})
            self.last_error = None
            return True
        except Exception as e:
            self.last_error = self.redactor.redact(str(e))
            logger.error("Press Enter failed: %s", type(e).__name__)
            return False

    async def scroll(self, direction: str, amount: int) -> bool:
        try:
            direction = direction.lower()
            dx, dy = 0, 0
            if direction == "down":
                dy = amount
            elif direction == "up":
                dy = -amount
            elif direction == "right":
                dx = amount
            elif direction == "left":
                dx = -amount
            else:
                raise ValueError(f"Unsupported scroll direction: {direction}")

            await self.page.evaluate(
                "({dx, dy}) => window.scrollBy(dx, dy)", {"dx": dx, "dy": dy}
            )
            logger.info(f"Scrolled {direction} by {amount}")
            self._record({"action": "scroll", "direction": direction, "amount": amount})
            self.last_error = None
            return True
        except Exception as e:
            self.last_error = self.redactor.redact(str(e))
            logger.error("Scroll failed: %s", type(e).__name__)
            return False

    async def wait(self, seconds: float) -> bool:
        try:
            await self.page.wait_for_timeout(int(seconds * 1000))
            self._record({"action": "wait", "seconds": seconds})
            self.last_error = None
            return True
        except Exception as e:
            self.last_error = self.redactor.redact(str(e))
            logger.error("Wait failed: %s", type(e).__name__)
            return False

    async def extract(self, selector: str, attr: str) -> Tuple[bool, Optional[str]]:
        try:
            resolved = await self._resolve_selector(selector)
            if not resolved:
                self.last_error = self.redactor.redact(
                    f"Selector not found: {selector}"
                )
                logger.error(self.last_error)
                return False, None
            attr_lower = attr.lower()
            if attr_lower in {"text", "innertext", "textcontent"}:
                script = "el => el.innerText"
                value = await self.page.eval_on_selector(resolved, script)
            elif attr_lower == "value":
                script = "el => el.value"
                value = await self.page.eval_on_selector(resolved, script)
            else:
                value = await self.page.eval_on_selector(
                    resolved, "(el, attr) => el.getAttribute(attr)", attr
                )

            self._record(
                {
                    "action": "extract",
                    "selector": resolved,
                    "attr": attr,
                    "value": value,
                }
            )
            self.last_error = None
            return True, value
        except Exception as e:
            self.last_error = self.redactor.redact(str(e))
            logger.error("Extract failed: %s", type(e).__name__)
            return False, None

    async def extract_all(self, selector: str, attr: str) -> Tuple[bool, List[str]]:
        """Extract attribute values from all matching elements."""
        try:
            attr_lower = attr.lower()
            if attr_lower in {"text", "innertext", "textcontent"}:
                script = "els => els.map(el => el.innerText)"
            elif attr_lower == "value":
                script = "els => els.map(el => el.value)"
            else:
                script = "(els, attr) => els.map(el => el.getAttribute(attr))"

            values = await self.page.eval_on_selector_all(selector, script, attr)
            self._record(
                {
                    "action": "extract_all",
                    "selector": selector,
                    "attr": attr,
                    "values": values,
                }
            )
            self.last_error = None
            return True, values
        except Exception as e:
            self.last_error = self.redactor.redact(str(e))
            logger.error("Extract all failed: %s", type(e).__name__)
            return False, []

    async def get_element_bounds(self, selector: str) -> Optional[Dict[str, float]]:
        """Get bounding box of element for coordinate-based fallback."""
        try:
            locator = self.page.locator(selector)
            if await locator.count() == 0:
                return None
            box = await locator.first.bounding_box()
            if box:
                viewport = self.page.viewport_size or {
                    "width": config.browser.viewport_width,
                    "height": config.browser.viewport_height,
                }
                # Return normalized center coordinates
                return {
                    "x": (box["x"] + box["width"] / 2) / viewport["width"],
                    "y": (box["y"] + box["height"] / 2) / viewport["height"],
                    "width": box["width"],
                    "height": box["height"],
                }
            return None
        except Exception as e:
            logger.warning("Could not get element bounds: %s", type(e).__name__)
            return None

    async def scan_interactive_elements(
        self, max_elements: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Scan the page for interactive elements and return their selectors and info.

        Returns a list of dicts with:
        - selector: CSS selector or Playwright locator string
        - tag: element tag name
        - type: input type (if applicable)
        - role: ARIA role
        - text: visible text content (truncated)
        - placeholder: placeholder text
        - aria_label: aria-label attribute
        - name: name attribute
        - id: id attribute
        """
        elements = []

        try:
            # Query all interactive elements
            interactive_script = (
                """
            () => {
                const elements = [];
                const selectors = [
                    'button', 'input', 'textarea', 'select', 'a[href]',
                    '[role="button"]', '[role="link"]', '[role="textbox"]',
                    '[onclick]', '[tabindex]', 'summary'
                ];

                const seen = new Set();

                for (const sel of selectors) {
                    const nodes = document.querySelectorAll(sel);
                    for (const el of nodes) {
                        // Skip if not visible
                        const rect = el.getBoundingClientRect();
                        if (rect.width === 0 || rect.height === 0) continue;
                        if (rect.bottom < 0 || rect.top > window.innerHeight) continue;

                        // Generate unique selector
                        let selector = '';
                        if (el.id) {
                            selector = '#' + CSS.escape(el.id);
                        } else if (el.name) {
                            selector = el.tagName.toLowerCase() + '[name="' + el.name + '"]';
                        } else if (el.getAttribute('aria-label')) {
                            selector = el.tagName.toLowerCase() + '[aria-label="' + el.getAttribute('aria-label') + '"]';
                        } else if (el.getAttribute('placeholder')) {
                            selector = el.tagName.toLowerCase() + '[placeholder*="' + el.getAttribute('placeholder').substring(0, 20) + '"]';
                        } else if (el.className && typeof el.className === 'string') {
                            const classes = el.className.split(' ').filter(c => c && !c.includes(':')).slice(0, 2);
                            if (classes.length > 0) {
                                selector = '.' + classes.map(c => CSS.escape(c)).join('.');
                            }
                        }

                        if (!selector || seen.has(selector)) continue;
                        seen.add(selector);

                        const info = {
                            selector: selector,
                            tag: el.tagName.toLowerCase(),
                            type: el.type || null,
                            role: el.getAttribute('role'),
                            text: (el.innerText || el.value || '').trim().substring(0, 50),
                            placeholder: el.getAttribute('placeholder'),
                            aria_label: el.getAttribute('aria-label'),
                            name: el.name,
                            id: el.id,
                            title: el.title,
                            href: el.href || null
                        };

                        elements.push(info);
                        if (elements.length >= %d) return elements;
                    }
                }
                return elements;
            }
            """
                % max_elements
            )

            elements = await self.page.evaluate(interactive_script)

            # Add Playwright role-based locators for better reliability
            for el in elements:
                el["playwright_locator"] = self._generate_playwright_locator(el)

            logger.info(f"Scanned {len(elements)} interactive elements")
            return elements

        except Exception as e:
            logger.error("Failed to scan interactive elements: %s", type(e).__name__)
            return []

    def _generate_playwright_locator(self, el: Dict[str, Any]) -> str:
        """Generate a Playwright locator string for an element."""
        # Prefer role-based locators
        if el.get("role"):
            role = el["role"]
            name = el.get("aria_label") or el.get("text") or el.get("name")
            if name:
                return f"getByRole('{role}', {{ name: '{name[:30]}' }})"
            return f"getByRole('{role}')"

        # Label-based for inputs
        if el.get("aria_label"):
            return f"getByLabel('{el['aria_label'][:30]}')"

        if el.get("placeholder"):
            return f"getByPlaceholder('{el['placeholder'][:30]}')"

        # Text-based for buttons/links
        if el.get("text") and el.get("tag") in ("button", "a"):
            text = el["text"].replace("'", "\\'")[:30]
            return f"getByText('{text}', {{ exact: false }})"

        # Fall back to CSS selector
        return el.get("selector", "")

    async def get_dom_context(self, max_elements: int = 50) -> str:
        """
        Get a formatted DOM context string for LLM prompting.

        Returns a concise summary of interactive elements on the page.
        """
        elements = await self.scan_interactive_elements(max_elements)

        if not elements:
            return "No interactive elements found."

        lines = ["Interactive elements on this page:"]
        lines.append("-" * 40)

        # Group by type
        buttons = [
            e for e in elements if e["tag"] == "button" or e.get("role") == "button"
        ]
        inputs = [e for e in elements if e["tag"] in ("input", "textarea", "select")]
        links = [e for e in elements if e["tag"] == "a"]
        others = [
            e
            for e in elements
            if e not in buttons and e not in inputs and e not in links
        ]

        if buttons:
            lines.append("\nBUTTONS:")
            for el in buttons[:10]:
                selector = el.get("selector", "")
                text = el.get("text", "")[:30]
                pw = el.get("playwright_locator", "")
                lines.append(f"  {selector}")
                if text:
                    lines.append(f'    text: "{text}"')
                if pw and pw != selector:
                    lines.append(f"    playwright: {pw}")

        if inputs:
            lines.append("\nINPUTS:")
            for el in inputs[:10]:
                selector = el.get("selector", "")
                input_type = el.get("type", "text")
                placeholder = el.get("placeholder", "")
                aria_label = el.get("aria_label", "")
                name = el.get("name", "")
                pw = el.get("playwright_locator", "")

                lines.append(f"  {selector} (type: {input_type})")
                if placeholder:
                    lines.append(f'    placeholder: "{placeholder}"')
                if aria_label:
                    lines.append(f'    aria-label: "{aria_label}"')
                if name:
                    lines.append(f'    name: "{name}"')
                if pw and pw != selector:
                    lines.append(f"    playwright: {pw}")

        if links:
            lines.append("\nLINKS:")
            for el in links[:5]:
                selector = el.get("selector", "")
                text = el.get("text", "")[:30]
                href = el.get("href", "")[:50]
                lines.append(f"  {selector}")
                if text:
                    lines.append(f'    text: "{text}"')
                if href:
                    lines.append(f"    href: {href}")

        if others:
            lines.append("\nOTHER INTERACTIVE:")
            for el in others[:5]:
                selector = el.get("selector", "")
                tag = el.get("tag", "")
                lines.append(f"  {selector} ({tag})")

        return "\n".join(lines)

    async def detect_captcha(self) -> bool:
        try:
            iframe_locator = self.page.locator("iframe")
            count = await iframe_locator.count()
            for i in range(count):
                frame = iframe_locator.nth(i)
                src = (await frame.get_attribute("src")) or ""
                title = (await frame.get_attribute("title")) or ""
                aria = (await frame.get_attribute("aria-label")) or ""
                hay = f"{src} {title} {aria}".lower()
                if "recaptcha" in hay or "hcaptcha" in hay or "captcha" in hay:
                    return True

            body_text = (await self.page.text_content("body")) or ""
            if "captcha" in body_text.lower():
                return True
        except Exception as e:
            logger.warning("Captcha detection failed: %s", type(e).__name__)
        return False

    async def click_first_checkbox(self) -> bool:
        try:
            locator = self.page.locator("input[type='checkbox']")
            count = await locator.count()
            for i in range(count):
                checkbox = locator.nth(i)
                if not await checkbox.is_visible():
                    continue
                if await checkbox.is_disabled():
                    continue
                if await checkbox.is_checked():
                    continue
                await checkbox.scroll_into_view_if_needed()
                await checkbox.click()
                logger.info("Auto-checked a checkbox")
                self._record(
                    {"action": "click", "selector": f"input[type=checkbox] >> nth={i}"}
                )
                return True
        except Exception as e:
            logger.error("Auto checkbox click failed: %s", type(e).__name__)
        return False

    async def _selector_exists(self, selector: str) -> bool:
        try:
            locator = self.page.locator(selector)
            return await locator.count() > 0
        except Exception as e:
            self.last_error = self.redactor.redact(str(e))
            logger.error("Selector check failed: %s", type(e).__name__)
            return False

    async def _resolve_selector(self, selector: str) -> Optional[str]:
        if await self._selector_exists(selector):
            return selector

        for alt in self._selector_alternatives(selector):
            if await self._selector_exists(alt):
                logger.info(
                    "Selector fallback: %s -> %s",
                    self.redactor.redact(selector),
                    self.redactor.redact(alt),
                )
                return alt

        return None

    def _resolve_coordinates(self, x: float, y: float) -> Tuple[int, int]:
        if 0 <= x <= 1 or 0 <= y <= 1:
            viewport = self.page.viewport_size or {
                "width": config.browser.viewport_width,
                "height": config.browser.viewport_height,
            }
            if 0 <= x <= 1:
                x = x * viewport["width"]
            if 0 <= y <= 1:
                y = y * viewport["height"]
        return int(x), int(y)

    @staticmethod
    def _selector_alternatives(selector: str) -> List[str]:
        alts: List[str] = []
        lowered = selector.lower()
        if 'placeholder="search"' in lowered or "placeholder='search'" in lowered:
            alts.extend(
                [
                    "#APjFqb",
                    "textarea[name='q']",
                    "input[name='q']",
                    "textarea[aria-label='Search']",
                    "textarea[role='combobox']",
                    "textarea[title='Search']",
                    "input[title='Search']",
                    "textarea",
                    "input[type='text']",
                ]
            )
        if 'name="q"' in lowered or "name='q'" in lowered:
            alts.extend(
                [
                    "#APjFqb",
                    "textarea[name='q']",
                    "input[name='q']",
                    "textarea[aria-label='Search']",
                    "textarea[role='combobox']",
                    "textarea",
                ]
            )
        return alts

    async def take_screenshot(self, name: Optional[str] = None) -> str:
        filename = name or datetime.now().strftime("%H%M%S")
        path = Path(config.browser.screenshot_dir) / f"{self.session_id}_{filename}.png"
        await self.page.screenshot(path=str(path))
        self.screenshot_paths.append(str(path))
        return str(path)

    async def get_page_text(self) -> str:
        return await self.page.evaluate("() => document.body.innerText")

    async def get_page_state(self) -> Dict[str, Any]:
        return {
            "url": self.page.url,
            "title": await self.page.title(),
            "text": await self.get_page_text(),
        }

    def save_transcript(self) -> str:
        path = (
            Path(config.browser.transcript_dir) / f"{self.session_id}_transcript.json"
        )
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.redactor.redact(self.transcript), f, indent=2)
        return str(path)

    async def _collect_videos(self):
        if self.page and self.page.video:
            try:
                path = await self.page.video.path()
                if path:
                    self.video_paths.append(str(path))
            except Exception as e:
                logger.warning("Unable to collect video path: %s", type(e).__name__)

    async def close(self) -> Dict[str, Any]:
        if self.page and not self.page.is_closed():
            await self.page.close()

        if self.context:
            try:
                if (
                    config.browser.reuse_storage_state
                    and config.browser.storage_state_path
                ):
                    await self.context.storage_state(
                        path=config.browser.storage_state_path
                    )
            except Exception as e:
                logger.warning("Failed to save storage state: %s", type(e).__name__)

        await self._collect_videos()

        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

        transcript_path = self.save_transcript()
        return {"videos": self.video_paths, "transcript": transcript_path}
