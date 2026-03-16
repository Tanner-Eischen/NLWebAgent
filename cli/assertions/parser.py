"""
Semantic assertion parser.

Parses natural language assertion expressions into structured data.
"""
import re
from typing import Dict, Optional, Any
from enum import Enum


class AssertionType(str, Enum):
    NUMERIC_COMPARISON = "numeric_comparison"
    STRING_MATCH = "string_match"
    VISIBILITY = "visibility"
    COUNT = "count"
    EXISTS = "exists"
    CUSTOM = "custom"


class ComparisonOperator(str, Enum):
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="
    EQ = "=="
    EQ_ALT = "="


class StringOperator(str, Enum):
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    EQUALS = "equals"


class ParsedAssertion:
    """Represents a parsed assertion expression."""

    def __init__(
        self,
        assertion_type: AssertionType,
        raw: str,
        field: Optional[str] = None,
        operator: Optional[str] = None,
        threshold: Optional[float] = None,
        pattern: Optional[str] = None,
        element: Optional[str] = None,
        selector: Optional[str] = None,
        expected_state: Optional[str] = None,
    ):
        self.type = assertion_type
        self.raw = raw
        self.field = field
        self.operator = operator
        self.threshold = threshold
        self.pattern = pattern
        self.element = element
        self.selector = selector
        self.expected_state = expected_state

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "raw": self.raw,
            "field": self.field,
            "operator": self.operator,
            "threshold": self.threshold,
            "pattern": self.pattern,
            "element": self.element,
            "selector": self.selector,
            "expected_state": self.expected_state,
        }


def parse_assertion(assertion: str) -> ParsedAssertion:
    """
    Parse an assertion string into a ParsedAssertion object.

    Supports formats:
    - Numeric: "price < 50", "count >= 5"
    - String: "title contains 'Sale'", "url starts with 'https'"
    - Visibility: "button is visible", "form is hidden"
    - Count: "count(.item) >= 3"
    - Exists: "element exists", "#submit exists"

    Args:
        assertion: Natural language assertion string

    Returns:
        ParsedAssertion object with parsed components
    """
    assertion = assertion.strip()

    # Try numeric comparison: field <op> number
    parsed = _try_parse_numeric(assertion)
    if parsed:
        return parsed

    # Try string matching: field operator 'pattern'
    parsed = _try_parse_string(assertion)
    if parsed:
        return parsed

    # Try visibility: element is visible/hidden
    parsed = _try_parse_visibility(assertion)
    if parsed:
        return parsed

    # Try count: count(selector) <op> number
    parsed = _try_parse_count(assertion)
    if parsed:
        return parsed

    # Try exists: element exists
    parsed = _try_parse_exists(assertion)
    if parsed:
        return parsed

    # Default: treat as visibility check
    return ParsedAssertion(
        assertion_type=AssertionType.VISIBILITY,
        raw=assertion,
        element=assertion,
        expected_state="visible",
    )


def _try_parse_numeric(assertion: str) -> Optional[ParsedAssertion]:
    """Try to parse as numeric comparison."""
    pattern = r"^(\w+)\s*(<|<=|>|>=|==|=)\s*(\d+(?:\.\d+)?)$"
    match = re.match(pattern, assertion)
    if match:
        return ParsedAssertion(
            assertion_type=AssertionType.NUMERIC_COMPARISON,
            raw=assertion,
            field=match.group(1),
            operator=match.group(2),
            threshold=float(match.group(3)),
        )
    return None


def _try_parse_string(assertion: str) -> Optional[ParsedAssertion]:
    """Try to parse as string matching."""
    pattern = (
        r"^(\w+)\s+(contains|starts?\s*with|ends?\s*with|equals|==)\s+['\"](.+?)['\"]$"
    )
    match = re.match(pattern, assertion, re.IGNORECASE)
    if match:
        operator = match.group(2).lower().replace(" ", "_")
        if operator == "start_with":
            operator = "starts_with"
        elif operator == "end_with":
            operator = "ends_with"
        return ParsedAssertion(
            assertion_type=AssertionType.STRING_MATCH,
            raw=assertion,
            field=match.group(1),
            operator=operator,
            pattern=match.group(3),
        )
    return None


def _try_parse_visibility(assertion: str) -> Optional[ParsedAssertion]:
    """Try to parse as visibility check."""
    pattern = r"^(.+?)\s+is\s+(visible|hidden|not\s+visible)$"
    match = re.match(pattern, assertion, re.IGNORECASE)
    if match:
        state = match.group(2).lower()
        if state == "not visible":
            state = "hidden"
        return ParsedAssertion(
            assertion_type=AssertionType.VISIBILITY,
            raw=assertion,
            element=match.group(1).strip(),
            expected_state=state,
        )
    return None


def _try_parse_count(assertion: str) -> Optional[ParsedAssertion]:
    """Try to parse as count assertion."""
    pattern = r"^count\((.+?)\)\s*(<|<=|>|>=|==|=)\s*(\d+)$"
    match = re.match(pattern, assertion, re.IGNORECASE)
    if match:
        return ParsedAssertion(
            assertion_type=AssertionType.COUNT,
            raw=assertion,
            selector=match.group(1),
            operator=match.group(2),
            threshold=int(match.group(3)),
        )
    return None


def _try_parse_exists(assertion: str) -> Optional[ParsedAssertion]:
    """Try to parse as existence check."""
    pattern = r"^(.+?)\s+exists$"
    match = re.match(pattern, assertion, re.IGNORECASE)
    if match:
        return ParsedAssertion(
            assertion_type=AssertionType.EXISTS,
            raw=assertion,
            element=match.group(1).strip(),
        )
    return None


def validate_assertion(assertion: str) -> tuple[bool, Optional[str]]:
    """
    Validate an assertion string.

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        parsed = parse_assertion(assertion)
        if parsed.type == AssertionType.CUSTOM:
            return False, f"Could not parse assertion: {assertion}"
        return True, None
    except Exception as e:
        return False, str(e)
