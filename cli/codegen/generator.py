"""Generate replayable Playwright source from successful execution events."""

import json
import math
import re
from typing import Any, Dict, List, Optional

from agent.actions import ActionParseError, ActionType, parse_action

_REFERENCE = re.compile(r"\$\{ENV:([A-Za-z_][A-Za-z0-9_]*)\}")


def _value(value: str, input_name: Optional[str] = None) -> str:
    """Serialize JavaScript data, substituting explicit runtime secret references."""
    value = str(value)
    if input_name is not None and not _REFERENCE.fullmatch(value):
        # Legacy recordings may predate redaction. Never embed typed literals.
        return f"requiredEnv({json.dumps(input_name)})"
    if "[REDACTED]" in value or "<typed_text>" in value:
        if input_name is None:
            raise ValueError(
                "Replay target was redacted; supply an explicit environment reference"
            )
        return f"requiredEnv({json.dumps(input_name)})"
    pieces = []
    end = 0
    for match in _REFERENCE.finditer(value):
        if match.start() > end:
            pieces.append(json.dumps(value[end : match.start()]))
        pieces.append(f"requiredEnv({json.dumps(match[1])})")
        end = match.end()
    if not pieces:
        return json.dumps(value)
    if end < len(value):
        pieces.append(json.dumps(value[end:]))
    return " + ".join(pieces)


def _coordinate(value: float, axis: str, space: str) -> str:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("Replay coordinates must be finite and nonnegative")
    if space == "pixels" or number > 1:
        return str(int(number))
    if space not in {"normalized", "auto"}:
        raise ValueError("Unknown coordinate space")
    return f"Math.trunc({number} * page.viewportSize().{axis})"


def _event_code(event: dict, index: int) -> str:
    kind = event.get("action", "").lower()
    if kind == "navigate":
        return f"await page.goto({_value(event['url'])});"
    if kind == "click":
        return f"await page.click({_value(event['selector'])});"
    if kind in {"type", "type_at"}:
        text = _value(event.get("text", "[REDACTED]"), f"NLWA_INPUT_{index + 1}")
        if kind == "type":
            selector = _value(event["selector"])
            return f'await page.fill({selector}, ""); await page.type({selector}, {text}, {{ delay: 50 }});'
    if kind in {"click_at", "type_at"}:
        space = event.get("coordinate_space", "auto")
        x = _coordinate(event["x"], "width", space)
        y = _coordinate(event["y"], "height", space)
        code = f"await page.mouse.click({x}, {y});"
        if kind == "type_at":
            code += f" await page.keyboard.type({text}, {{ delay: 50 }});"
        return code
    if kind == "press_enter":
        return 'await page.keyboard.press("Enter");'
    if kind == "scroll":
        amount = int(event["amount"])
        if amount <= 0:
            raise ValueError("Scroll amount must be positive")
        offsets = {
            "down": (0, amount),
            "up": (0, -amount),
            "left": (-amount, 0),
            "right": (amount, 0),
        }
        dx, dy = offsets[event["direction"]]
        return f"await page.evaluate(([x, y]) => window.scrollBy(x, y), [{dx}, {dy}]);"
    if kind == "wait":
        seconds = float(event["seconds"])
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("Wait must be finite and positive")
        return f"await page.waitForTimeout({int(seconds * 1000)});"
    if kind == "extract":
        locator = f"page.locator({_value(event['selector'])}).first()"
        attr = event.get("attr", "text")
        if attr.lower() in {"text", "innertext", "textcontent"}:
            read = f"{locator}.innerText()"
        elif attr.lower() == "value":
            read = f"{locator}.inputValue()"
        else:
            read = f"{locator}.getAttribute({_value(attr)})"
        return f"const value{index} = await {read};"
    if kind == "done":
        return "// Agent finished; outcome assertions are separate."
    raise ValueError(f"Unsupported replay action: {kind}")


def _legacy_event(entry: dict) -> Optional[dict]:
    if entry.get("status", "success") != "success":
        return None
    raw = entry.get("parsed_action")
    if raw:
        action = parse_action(json.dumps(raw))
    else:
        action = parse_action(entry.get("action", ""))
    event = action.model_dump(mode="json")
    kind = event.pop("type").lower()
    event["action"] = "type" if kind == "type" else kind
    if action.type == ActionType.ERROR:
        return None
    return event


def generate_playwright_test(
    recording: Dict[str, Any],
    test_name: str = "test_recorded",
    add_assertions: bool = True,
) -> str:
    """Prefer actual browser events over the model's proposed action history.

    Typed values are references to environment variables. Missing values fail
    explicitly instead of replaying a redaction placeholder as literal input.
    """
    if "transcript" in recording:
        events = [
            event
            for event in recording["transcript"]
            if event.get("status", "success") == "success"
        ]
    else:
        events = []
        for entry in recording.get("actions", []):
            event = _legacy_event(entry)
            if event is not None:
                events.append(event)
    url = recording.get("url", "")
    if url and (not events or events[0].get("action") != "navigate"):
        events.insert(0, {"action": "navigate", "url": url})
    viewport = recording.get("viewport") or next(
        (event["viewport"] for event in events if event.get("viewport")), None
    )
    lines = [
        "// Generated by NLWebAgent. Supply referenced environment variables before replay.",
        "import { test, expect } from '@playwright/test';",
        "",
        "function requiredEnv(name) {",
        "  const value = process.env[name];",
        "  if (!value) throw new Error(`Missing replay environment variable: ${name}`);",
        "  return value;",
        "}",
        "",
    ]
    if viewport:
        lines.append(f"test.use({{ viewport: {json.dumps(viewport)} }});")
    lines.append(f"test({json.dumps(test_name)}, async ({{ page }}) => {{")
    for index, event in enumerate(events):
        lines.append("  " + _event_code(event, index))
    if add_assertions:
        if recording.get("final_url"):
            lines.append(
                f"  await expect(page).toHaveURL({_value(recording['final_url'])});"
            )
        lines.append("  // Add explicit outcome assertions for the intended behavior.")
        for extraction in recording.get("extractions", []):
            if extraction.get("selector") and extraction.get("value") is not None:
                # Serialize the whole suggestion so user data cannot introduce source lines.
                suggestion = {
                    "selector": extraction["selector"],
                    "attr": extraction.get("attr", "text"),
                    "expected": extraction["value"],
                }
                lines.append("  // Suggested assertion data: " + json.dumps(suggestion))
    lines.extend(["});", ""])
    return "\n".join(lines)


def _convert_action_to_playwright(action: str, index: int) -> Optional[str]:
    if not action:
        return None
    try:
        event = _legacy_event({"action": action})
    except ActionParseError as exc:
        raise ValueError("Cannot export invalid action") from exc
    return _event_code(event, index) if event else None


def generate_test_from_transcript(
    transcript: List[Dict], url: str, test_name: str = "test_from_transcript"
) -> str:
    return generate_playwright_test({"url": url, "transcript": transcript}, test_name)
