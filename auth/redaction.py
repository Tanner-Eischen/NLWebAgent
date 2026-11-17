"""Secret references and redaction for persisted artifacts and model history."""

import json
import os
import re
from typing import Any
from urllib.parse import quote, quote_plus

_ENV_REFERENCE = re.compile(r"\$\{ENV:([A-Za-z_][A-Za-z0-9_]*)\}")
_METADATA_FIELDS = frozenset(
    {"status", "type", "model", "provider", "session_id", "coordinate_space"}
)
_ACTION_COMMANDS = frozenset(
    {
        "CLICK",
        "CLICK_AT",
        "TYPE",
        "TYPE_AT",
        "NAVIGATE",
        "SCROLL",
        "WAIT",
        "EXTRACT",
        "EXTRACT_ALL",
        "DONE",
        "ERROR",
        "PRESS_ENTER",
        "AUTO_CHECKBOX_CLICK",
    }
)


class SecretRedactor:
    """Keep known secret values out of text and nested result structures.

    Registration is explicit: this does not inspect the process environment.
    Callers should also avoid recording arbitrary typed text in the first place.
    """

    def __init__(self):
        self._replacements: dict[str, str] = {}

    def add(self, value: str, replacement: str = "[REDACTED]") -> None:
        if not value:
            return
        for variant in {value, quote(value, safe=""), quote_plus(value, safe="")}:
            if variant not in self._replacements or replacement != "[REDACTED]":
                self._replacements[variant] = replacement

    def redact(self, value: Any) -> Any:
        if isinstance(value, str):
            if not self._replacements:
                return value
            # One substitution pass avoids changing placeholders inserted for
            # another secret (including overlapping values).
            secrets = "|".join(
                re.escape(secret)
                for secret in sorted(self._replacements, key=len, reverse=True)
            )
            # Preserve references on repeated passes through reporting layers.
            pattern = _ENV_REFERENCE.pattern + r"|\[REDACTED\]|" + secrets
            return re.sub(
                pattern,
                lambda match: self._replacements.get(match[0], match[0]),
                value,
            )
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key in _METADATA_FIELDS:
                    result[key] = item
                elif key == "action" and isinstance(item, str):
                    if item.lstrip().startswith("{"):
                        try:
                            parsed = json.loads(item)
                        except json.JSONDecodeError:
                            result[key] = self.redact(item)
                        else:
                            result[key] = json.dumps(self.redact(parsed))
                        continue
                    # Action command names are schema, not user-entered values.
                    command, separator, payload = item.partition(":")
                    result[key] = (
                        command + separator + self.redact(payload)
                        if command.upper() in _ACTION_COMMANDS
                        else self.redact(item)
                    )
                else:
                    result[key] = self.redact(item)
            return result
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact(item) for item in value)
        return value


def resolve_secret_references(text: str, redactor: SecretRedactor) -> str:
    """Resolve explicit ${ENV:NAME} tokens immediately before execution.

    Missing values raise an error naming only the variable, never its value.
    The value is registered for redaction before it leaves this function.
    """

    def replace(match: re.Match) -> str:
        name = match[1]
        value = os.getenv(name)
        if not value:
            raise ValueError(f"Missing secret environment variable: {name}")
        redactor.add(value, replacement=match[0])
        return value

    return _ENV_REFERENCE.sub(replace, text)
