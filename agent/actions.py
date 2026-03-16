from enum import Enum
from typing import Union, Literal

import re

from pydantic import BaseModel, ValidationError, field_validator


class ActionParseError(ValueError):
    pass


class ActionType(str, Enum):
    CLICK = "CLICK"
    CLICK_AT = "CLICK_AT"
    TYPE = "TYPE"
    TYPE_AT = "TYPE_AT"
    NAVIGATE = "NAVIGATE"
    SCROLL = "SCROLL"
    WAIT = "WAIT"
    EXTRACT = "EXTRACT"
    DONE = "DONE"
    ERROR = "ERROR"


class BaseAction(BaseModel):
    type: ActionType


class ClickAction(BaseAction):
    type: Literal[ActionType.CLICK]
    selector: str

    @field_validator("selector")
    @classmethod
    def _selector_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("selector is required")
        selector = value.strip()
        if selector.lower() == "selector":
            raise ValueError("selector placeholder is not valid")
        if _looks_like_action_list(selector):
            raise ValueError("selector appears to contain action list")
        _reject_overlong_selector(selector)
        return selector


class TypeAction(BaseAction):
    type: Literal[ActionType.TYPE]
    selector: str
    text: str

    @field_validator("selector")
    @classmethod
    def _type_selector_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("selector is required")
        selector = value.strip()
        if selector.lower() == "selector":
            raise ValueError("selector placeholder is not valid")
        if _looks_like_action_list(selector):
            raise ValueError("selector appears to contain action list")
        _reject_overlong_selector(selector)
        return selector

    @field_validator("text")
    @classmethod
    def _text_not_empty(cls, value: str) -> str:
        if value is None or value == "":
            raise ValueError("text is required")
        return value


class ClickAtAction(BaseAction):
    type: Literal[ActionType.CLICK_AT]
    x: float
    y: float

    @field_validator("x", "y", mode="before")
    @classmethod
    def _coordinate_valid(cls, value: object) -> float:
        try:
            coord = float(value)
        except (TypeError, ValueError):
            raise ValueError("coordinate must be a number")
        if coord < 0:
            raise ValueError("coordinate must be >= 0")
        return coord


class TypeAtAction(BaseAction):
    type: Literal[ActionType.TYPE_AT]
    x: float
    y: float
    text: str

    @field_validator("x", "y", mode="before")
    @classmethod
    def _coordinate_valid(cls, value: object) -> float:
        try:
            coord = float(value)
        except (TypeError, ValueError):
            raise ValueError("coordinate must be a number")
        if coord < 0:
            raise ValueError("coordinate must be >= 0")
        return coord

    @field_validator("text")
    @classmethod
    def _text_not_empty(cls, value: str) -> str:
        if value is None or value == "":
            raise ValueError("text is required")
        return value


class NavigateAction(BaseAction):
    type: Literal[ActionType.NAVIGATE]
    url: str

    @field_validator("url")
    @classmethod
    def _url_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("url is required")
        url = value.strip()
        if url.lower() == "url":
            raise ValueError("url placeholder is not valid")
        return url


class ScrollAction(BaseAction):
    type: Literal[ActionType.SCROLL]
    direction: str
    amount: int

    @field_validator("direction")
    @classmethod
    def _direction_valid(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("direction is required")
        value = value.strip().lower()
        if value in {"bottom"}:
            value = "down"
        elif value in {"top"}:
            value = "up"
        if value not in {"up", "down", "left", "right"}:
            raise ValueError("direction must be up, down, left, or right")
        return value

    @field_validator("amount", mode="before")
    @classmethod
    def _amount_valid(cls, value: object) -> int:
        try:
            amount = int(value)
        except (TypeError, ValueError):
            raise ValueError("amount must be an integer")
        if amount <= 0:
            raise ValueError("amount must be > 0")
        return amount


class WaitAction(BaseAction):
    type: Literal[ActionType.WAIT]
    seconds: float

    @field_validator("seconds", mode="before")
    @classmethod
    def _seconds_valid(cls, value: object) -> float:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            raise ValueError("seconds must be a number")
        if seconds <= 0:
            raise ValueError("seconds must be > 0")
        return seconds


class ExtractAction(BaseAction):
    type: Literal[ActionType.EXTRACT]
    selector: str
    attr: str

    @field_validator("selector")
    @classmethod
    def _extract_selector_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("selector is required")
        selector = value.strip()
        if selector.lower() == "selector":
            raise ValueError("selector placeholder is not valid")
        if _looks_like_action_list(selector):
            raise ValueError("selector appears to contain action list")
        _reject_overlong_selector(selector)
        return selector

    @field_validator("attr")
    @classmethod
    def _attr_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("attr is required")
        attr = value.strip()
        if attr.lower() == "attr":
            raise ValueError("attr placeholder is not valid")
        return attr


class DoneAction(BaseAction):
    type: Literal[ActionType.DONE]


class ErrorAction(BaseAction):
    type: Literal[ActionType.ERROR]
    message: str

    @field_validator("message")
    @classmethod
    def _message_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("message is required")
        return value.strip()


Action = Union[
    ClickAction,
    ClickAtAction,
    TypeAction,
    TypeAtAction,
    NavigateAction,
    ScrollAction,
    WaitAction,
    ExtractAction,
    DoneAction,
    ErrorAction,
]


def parse_action(raw: str) -> Action:
    if raw is None:
        raise ActionParseError("action is empty")

    text = _extract_action_line(raw)
    if not text:
        raise ActionParseError("action is empty")

    text = _strip_result_suffix(text)
    text = _strip_markdown_emphasis(text)
    upper = text.upper()

    try:
        if upper.startswith("DONE"):
            return DoneAction(type=ActionType.DONE)
        if upper.startswith("CLICK:"):
            selector = _normalize_field(text.split(":", 1)[1], "selector")
            return ClickAction(type=ActionType.CLICK, selector=selector)
        if upper.startswith("CLICK_AT:"):
            x_val, y_val = _split_xy(text)
            return ClickAtAction(type=ActionType.CLICK_AT, x=x_val, y=y_val)
        if upper.startswith("TYPE:"):
            parts = text.split(":", 2)
            if len(parts) < 3:
                raise ActionParseError("TYPE requires selector and text")
            selector = _normalize_field(parts[1], "selector")
            text_value = _normalize_field(parts[2], "text", strip_outer_quotes=True)
            return TypeAction(type=ActionType.TYPE, selector=selector, text=text_value)
        if upper.startswith("TYPE_AT:"):
            parts = text.split(":", 3)
            if len(parts) < 4:
                raise ActionParseError("TYPE_AT requires x, y, and text")
            x_val = _normalize_field(parts[1], "x")
            y_val = _normalize_field(parts[2], "y")
            text_value = _normalize_field(parts[3], "text", strip_outer_quotes=True)
            return TypeAtAction(
                type=ActionType.TYPE_AT, x=x_val, y=y_val, text=text_value
            )
        if upper.startswith("NAVIGATE:"):
            url = _normalize_field(text.split(":", 1)[1], "url")
            return NavigateAction(type=ActionType.NAVIGATE, url=url)
        if upper.startswith("SCROLL:"):
            parts = text.split(":", 2)
            if len(parts) < 3:
                raise ActionParseError("SCROLL requires direction and amount")
            direction = _normalize_field(parts[1], "direction")
            amount = _normalize_field(parts[2], "amount")
            return ScrollAction(
                type=ActionType.SCROLL, direction=direction, amount=amount
            )
        if upper.startswith("WAIT:"):
            seconds = _normalize_field(text.split(":", 1)[1], "seconds")
            return WaitAction(type=ActionType.WAIT, seconds=seconds)
        if upper.startswith("EXTRACT:"):
            parts = text.split(":", 2)
            if len(parts) < 3:
                raise ActionParseError("EXTRACT requires selector and attr")
            selector = _normalize_field(parts[1], "selector")
            attr = _normalize_field(parts[2], "attr")
            return ExtractAction(type=ActionType.EXTRACT, selector=selector, attr=attr)
        if upper.startswith("ERROR:"):
            message = _normalize_field(text.split(":", 1)[1], "message")
            return ErrorAction(type=ActionType.ERROR, message=message)
    except ValidationError as e:
        raise ActionParseError(str(e)) from e

    raise ActionParseError(f"Unsupported action: {text}")


def parse_action_lenient(raw: str) -> Action:
    if raw is None:
        raise ActionParseError("action is empty")

    text = _extract_action_line_lenient(raw)
    if not text:
        raise ActionParseError("action is empty")

    text = _strip_result_suffix(text)
    text = _strip_markdown_emphasis(text)
    upper = text.upper()

    try:
        if upper.startswith("DONE"):
            return DoneAction(type=ActionType.DONE)
        if upper.startswith("CLICK:"):
            selector = _normalize_field(text.split(":", 1)[1], "selector")
            return ClickAction(type=ActionType.CLICK, selector=selector)
        if upper.startswith("CLICK_AT:"):
            x_val, y_val = _split_xy(text)
            return ClickAtAction(type=ActionType.CLICK_AT, x=x_val, y=y_val)
        if upper.startswith("TYPE:"):
            parts = text.split(":", 2)
            if len(parts) < 3:
                raise ActionParseError("TYPE requires selector and text")
            selector = _normalize_field(parts[1], "selector")
            text_value = _normalize_field(parts[2], "text", strip_outer_quotes=True)
            return TypeAction(type=ActionType.TYPE, selector=selector, text=text_value)
        if upper.startswith("TYPE_AT:"):
            parts = text.split(":", 3)
            if len(parts) < 4:
                raise ActionParseError("TYPE_AT requires x, y, and text")
            x_val = _normalize_field(parts[1], "x")
            y_val = _normalize_field(parts[2], "y")
            text_value = _normalize_field(parts[3], "text", strip_outer_quotes=True)
            return TypeAtAction(
                type=ActionType.TYPE_AT, x=x_val, y=y_val, text=text_value
            )
        if upper.startswith("NAVIGATE:"):
            url = _normalize_field(text.split(":", 1)[1], "url")
            return NavigateAction(type=ActionType.NAVIGATE, url=url)
        if upper.startswith("SCROLL:"):
            parts = text.split(":", 2)
            if len(parts) < 3:
                raise ActionParseError("SCROLL requires direction and amount")
            direction = _normalize_field(parts[1], "direction")
            amount = _normalize_field(parts[2], "amount")
            return ScrollAction(
                type=ActionType.SCROLL, direction=direction, amount=amount
            )
        if upper.startswith("WAIT:"):
            seconds = _normalize_field(text.split(":", 1)[1], "seconds")
            return WaitAction(type=ActionType.WAIT, seconds=seconds)
        if upper.startswith("EXTRACT:"):
            parts = text.split(":", 2)
            if len(parts) < 3:
                raise ActionParseError("EXTRACT requires selector and attr")
            selector = _normalize_field(parts[1], "selector")
            attr = _normalize_field(parts[2], "attr")
            return ExtractAction(type=ActionType.EXTRACT, selector=selector, attr=attr)
        if upper.startswith("ERROR:"):
            message = _normalize_field(text.split(":", 1)[1], "message")
            return ErrorAction(type=ActionType.ERROR, message=message)
    except ValidationError as e:
        raise ActionParseError(str(e)) from e

    raise ActionParseError(f"Unsupported action: {text}")


def _strip_wrapped_quotes(value: str) -> str:
    if len(value) >= 2:
        if value[0] == value[-1] and value[0] in {'"', "'"}:
            return value[1:-1]
    return value


def _strip_key_prefix(value: str, key: str) -> str:
    if not value:
        return value
    stripped = value.strip()
    prefix = f"{key}="
    if stripped.lower().startswith(prefix):
        stripped = stripped[len(prefix) :].strip()
    return stripped


def _normalize_field(value: str, key: str, strip_outer_quotes: bool = True) -> str:
    if value is None:
        return ""
    normalized = _strip_key_prefix(value, key)
    normalized = normalized.strip()
    if strip_outer_quotes:
        normalized = _strip_wrapped_quotes(normalized).strip()
    if key == "selector":
        if normalized.startswith("<") and normalized.endswith(">"):
            normalized = normalized[1:-1].strip()
        normalized = _strip_selector_annotation(normalized)
    return normalized


def _looks_like_action_list(value: str) -> bool:
    upper = value.upper()
    if " | " in value:
        return True
    for token in (
        "CLICK:",
        "CLICK_AT:",
        "TYPE:",
        "TYPE_AT:",
        "NAVIGATE:",
        "SCROLL:",
        "WAIT:",
        "EXTRACT:",
        "DONE",
        "ERROR:",
    ):
        if token in upper:
            return True
    return False


def _extract_action_line(raw: str) -> str:
    if raw is None:
        return ""
    lines = [line.strip() for line in str(raw).splitlines() if line.strip()]
    if not lines:
        return ""

    action_lines = []
    for line in lines:
        if _is_ignorable_line(line):
            continue
        candidate = _strip_markdown_prefix(line)
        candidate = _strip_action_prefix(candidate)
        upper = candidate.upper()
        if upper.startswith(
            (
                "CLICK:",
                "CLICK_AT:",
                "TYPE:",
                "TYPE_AT:",
                "NAVIGATE:",
                "SCROLL:",
                "WAIT:",
                "EXTRACT:",
                "DONE",
                "ERROR:",
            )
        ):
            action_lines.append(candidate)

    if len(action_lines) > 1:
        raise ActionParseError("Multiple actions found; output exactly one action line")
    if len(action_lines) == 1:
        return action_lines[0]

    return lines[0]


def _extract_action_line_lenient(raw: str) -> str:
    if raw is None:
        return ""
    text = str(raw)
    for match in _ACTION_REGEX.finditer(text):
        start = match.start()
        end = text.find("\n", start)
        if end == -1:
            end = len(text)
        candidate = text[start:end].strip()
        if not _is_prompt_example(candidate):
            return candidate

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    for line in lines:
        if _is_ignorable_line(line):
            continue
        candidate = _strip_markdown_prefix(line)
        candidate = _strip_action_prefix(candidate)
        upper = candidate.upper()
        if upper.startswith(
            (
                "CLICK:",
                "CLICK_AT:",
                "TYPE:",
                "TYPE_AT:",
                "NAVIGATE:",
                "SCROLL:",
                "WAIT:",
                "EXTRACT:",
                "DONE",
                "ERROR:",
            )
        ):
            if not _is_prompt_example(candidate):
                return candidate
    return lines[0]


def _strip_markdown_prefix(line: str) -> str:
    stripped = line.lstrip()
    if stripped.startswith("```"):
        return ""
    for prefix in ("- ", "* ", "> ", "# ", "## ", "### "):
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].lstrip()
    if stripped[:2].isdigit() and stripped[2:3] == ".":
        return stripped[3:].lstrip()
    return stripped


def _strip_action_prefix(line: str) -> str:
    if not line:
        return line
    cleaned = _strip_markdown_emphasis(line).strip()
    upper = cleaned.upper()
    tokens = (
        "CLICK:",
        "CLICK_AT:",
        "TYPE:",
        "TYPE_AT:",
        "NAVIGATE:",
        "SCROLL:",
        "WAIT:",
        "EXTRACT:",
        "DONE",
        "ERROR:",
    )
    for token in tokens:
        idx = upper.find(token)
        if idx >= 0:
            return cleaned[idx:].strip()
    if upper.startswith("ACTION:"):
        return cleaned.split(":", 1)[1].strip()
    if upper.startswith("NEXT ACTION:"):
        return cleaned.split(":", 1)[1].strip()
    if upper.startswith("NEXT ACTION"):
        return cleaned.split(" ", 2)[-1].strip()

    url_match = re.search(r"(https?://\S+)", cleaned)
    if url_match and ("GO TO" in upper or "NAVIGATE" in upper):
        return f"NAVIGATE:{url_match.group(1)}"

    return cleaned


def _strip_result_suffix(line: str) -> str:
    if not line:
        return line
    lowered = line.lower()
    if "->" in line:
        head = line.split("->", 1)[0].strip()
        if head:
            return head
    for token in (" - success", " success", " - done", " done"):
        if lowered.endswith(token):
            return line[: -len(token)].strip()
    return line


def _strip_selector_annotation(selector: str) -> str:
    if not selector:
        return selector
    if ":" not in selector:
        return selector
    # Heuristic: strip trailing label like `selector: Label text`
    head, tail = selector.split(":", 1)
    if " " in tail and "(" not in tail:
        return head.strip()
    return selector


def _strip_markdown_emphasis(text: str) -> str:
    if not text:
        return text
    stripped = text.strip()
    if stripped.startswith("**") and stripped.endswith("**"):
        stripped = stripped[2:-2].strip()
    if stripped.startswith("`") and stripped.endswith("`"):
        stripped = stripped[1:-1].strip()
    if stripped.startswith("<") and stripped.endswith(">"):
        stripped = stripped[1:-1].strip()
    return stripped


def _split_xy(text: str) -> tuple[str, str]:
    parts = text.split(":", 3)
    if len(parts) < 3:
        raise ActionParseError("CLICK_AT requires x and y")
    x_val = _clean_number_token(_normalize_field(parts[1], "x"))
    y_raw = parts[2]
    y_token = y_raw.split(":", 1)[0]
    y_val = _clean_number_token(_normalize_field(y_token, "y"))
    return x_val, y_val


def _clean_number_token(token: str) -> str:
    if not token:
        return token
    return "".join(ch for ch in token if ch.isdigit() or ch in ".-")


def _reject_overlong_selector(selector: str) -> None:
    if len(selector) > 200 or selector.count(">") > 6:
        raise ValueError("selector is too long; use a simpler selector or CLICK_AT")


def _is_ignorable_line(line: str) -> bool:
    cleaned = _strip_markdown_prefix(line)
    cleaned = _strip_markdown_emphasis(cleaned).strip()
    upper = cleaned.upper()
    if not upper:
        return True
    if upper.startswith("INFO:"):
        return True
    if upper.startswith("NOTE:"):
        return True
    if upper.startswith("RETURN EXACTLY"):
        return True
    if upper.startswith("RULES:"):
        return True
    if upper in {"ACTION:", "NEXT ACTION:", "NEXT ACTION", "ACTION"}:
        return True
    if "search button" in cleaned.lower():
        return True
    if not any(
        token in upper
        for token in (
            "CLICK",
            "CLICK_AT",
            "TYPE",
            "TYPE_AT",
            "NAVIGATE",
            "SCROLL",
            "WAIT",
            "EXTRACT",
            "DONE",
            "ERROR",
        )
    ):
        if cleaned.endswith(".") or cleaned.endswith(":"):
            return True
    if any(
        token in line
        for token in (
            "<css selector>",
            "<url>",
            "<pixels>",
            "<seconds>",
            "<attr>",
            "<x>",
            "<y>",
            "<text>",
        )
    ):
        return True
    return False


_ACTION_REGEX = re.compile(
    r"(CLICK_AT|TYPE_AT|CLICK|TYPE|NAVIGATE|SCROLL|WAIT|EXTRACT|DONE|ERROR)\s*:\s*.*",
    re.IGNORECASE,
)


def _is_prompt_example(line: str) -> bool:
    if not line:
        return False
    return any(
        token in line
        for token in (
            "<css selector>",
            "<url>",
            "<pixels>",
            "<seconds>",
            "<attr>",
            "<x>",
            "<y>",
            "<text>",
        )
    )
