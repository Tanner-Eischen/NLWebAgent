"""
Semantic assertion evaluator.

Evaluates parsed assertions against a web page.
"""
import re
from typing import Dict, Any, Optional

from cli.assertions.parser import (
    ParsedAssertion,
    AssertionType,
)


class AssertionResult:
    """Result of evaluating an assertion."""

    def __init__(
        self,
        passed: bool,
        actual_value: Any = None,
        expected_value: Any = None,
        error: Optional[str] = None,
    ):
        self.passed = passed
        self.actual_value = actual_value
        self.expected_value = expected_value
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "actual_value": self.actual_value,
            "expected_value": self.expected_value,
            "error": self.error,
        }


class AssertionEvaluator:
    """Evaluates assertions against a browser page."""

    # Maps field names to common selectors
    FIELD_SELECTORS = {
        "price": ".price, [class*='price'], #price, [data-price]",
        "count": ".count, [class*='count'], #count",
        "total": ".total, [class*='total'], #total",
        "quantity": ".quantity, [class*='quantity'], #quantity",
        "title": "title, h1, .title, #title",
        "heading": "h1, h2, .heading, #heading",
        "name": ".name, [class*='name'], #name",
        "email": "input[type='email'], .email, #email",
        "text": "body",
    }

    # Maps element names to common selectors
    ELEMENT_SELECTORS = {
        "button": "button, input[type='submit'], input[type='button'], .btn, .button, #submit",
        "form": "form, .form",
        "link": "a, .link",
        "input": "input, textarea, select",
        "image": "img",
        "text": "body",
        "error": ".error, .alert-error, [class*='error'], .alert-danger",
        "success": ".success, .alert-success, [class*='success']",
        "warning": ".warning, .alert-warning, [class*='warning']",
        "modal": ".modal, [role='dialog'], .dialog",
        "menu": "nav, .menu, .nav",
        "header": "header, .header",
        "footer": "footer, .footer",
    }

    def __init__(self, browser):
        """
        Initialize the evaluator.

        Args:
            browser: BrowserController instance
        """
        self.browser = browser

    async def evaluate(self, assertion: ParsedAssertion) -> AssertionResult:
        """
        Evaluate a parsed assertion against the current page.

        Args:
            assertion: ParsedAssertion to evaluate

        Returns:
            AssertionResult with pass/fail status and details
        """
        try:
            if assertion.type == AssertionType.NUMERIC_COMPARISON:
                return await self._evaluate_numeric(assertion)

            elif assertion.type == AssertionType.STRING_MATCH:
                return await self._evaluate_string(assertion)

            elif assertion.type == AssertionType.VISIBILITY:
                return await self._evaluate_visibility(assertion)

            elif assertion.type == AssertionType.COUNT:
                return await self._evaluate_count(assertion)

            elif assertion.type == AssertionType.EXISTS:
                return await self._evaluate_exists(assertion)

            else:
                return AssertionResult(
                    passed=False,
                    error=f"Unknown assertion type: {assertion.type}",
                )

        except Exception as e:
            return AssertionResult(passed=False, error=str(e))

    async def _evaluate_numeric(self, assertion: ParsedAssertion) -> AssertionResult:
        """Evaluate a numeric comparison assertion."""
        value = await self._extract_numeric_value(assertion.field)

        if value is None:
            return AssertionResult(
                passed=False,
                error=f"Could not extract numeric value for field: {assertion.field}",
            )

        passed = self._compare_numeric(value, assertion.operator, assertion.threshold)

        return AssertionResult(
            passed=passed,
            actual_value=value,
            expected_value=f"{assertion.operator} {assertion.threshold}",
        )

    async def _evaluate_string(self, assertion: ParsedAssertion) -> AssertionResult:
        """Evaluate a string matching assertion."""
        value = await self._extract_string_value(assertion.field)

        if value is None:
            return AssertionResult(
                passed=False,
                error=f"Could not extract string value for field: {assertion.field}",
            )

        passed = self._match_string(value, assertion.operator, assertion.pattern)

        return AssertionResult(
            passed=passed,
            actual_value=value,
            expected_value=f"{assertion.operator} '{assertion.pattern}'",
        )

    async def _evaluate_visibility(self, assertion: ParsedAssertion) -> AssertionResult:
        """Evaluate a visibility assertion."""
        selector = self._get_element_selector(assertion.element)
        visible = await self._check_visibility(selector)

        expected_visible = assertion.expected_state == "visible"
        passed = visible == expected_visible

        return AssertionResult(
            passed=passed,
            actual_value="visible" if visible else "hidden",
            expected_value=assertion.expected_state,
        )

    async def _evaluate_count(self, assertion: ParsedAssertion) -> AssertionResult:
        """Evaluate a count assertion."""
        count = await self._count_elements(assertion.selector)
        passed = self._compare_numeric(count, assertion.operator, assertion.threshold)

        return AssertionResult(
            passed=passed,
            actual_value=count,
            expected_value=f"{assertion.operator} {assertion.threshold}",
        )

    async def _evaluate_exists(self, assertion: ParsedAssertion) -> AssertionResult:
        """Evaluate an existence assertion."""
        selector = self._get_element_selector(assertion.element)
        exists = await self._element_exists(selector)

        return AssertionResult(
            passed=exists,
            actual_value="exists" if exists else "not found",
            expected_value="exists",
        )

    async def _extract_numeric_value(self, field: str) -> Optional[float]:
        """Extract a numeric value from the page."""
        selector = self.FIELD_SELECTORS.get(field.lower(), f".{field}, #{field}")

        ok, text = await self.browser.extract(selector, "text")
        if ok and text:
            # Extract first number from text
            numbers = re.findall(r"[\d,.]+", text)
            if numbers:
                try:
                    return float(numbers[0].replace(",", ""))
                except ValueError:
                    pass
        return None

    async def _extract_string_value(self, field: str) -> Optional[str]:
        """Extract a string value from the page."""
        if field.lower() == "url":
            return self.browser.page.url if self.browser.page else None

        selector = self.FIELD_SELECTORS.get(field.lower(), f".{field}, #{field}")
        ok, text = await self.browser.extract(selector, "text")
        return text if ok else None

    async def _check_visibility(self, selector: str) -> bool:
        """Check if an element is visible."""
        try:
            locator = self.browser.page.locator(selector)
            return await locator.first.is_visible()
        except Exception:
            return False

    async def _count_elements(self, selector: str) -> int:
        """Count elements matching selector."""
        try:
            locator = self.browser.page.locator(selector)
            return await locator.count()
        except Exception:
            return 0

    async def _element_exists(self, selector: str) -> bool:
        """Check if an element exists."""
        try:
            locator = self.browser.page.locator(selector)
            return await locator.count() > 0
        except Exception:
            return False

    def _get_element_selector(self, element: str) -> str:
        """Convert element name to selector."""
        if element.startswith(("#", ".", "[")):
            return element
        return self.ELEMENT_SELECTORS.get(element.lower(), element)

    @staticmethod
    def _compare_numeric(value: float, operator: str, threshold: float) -> bool:
        """Compare numeric values."""
        ops = {
            "<": lambda a, b: a < b,
            "<=": lambda a, b: a <= b,
            ">": lambda a, b: a > b,
            ">=": lambda a, b: a >= b,
            "==": lambda a, b: a == b,
            "=": lambda a, b: a == b,
        }
        return ops.get(operator, lambda a, b: False)(value, threshold)

    @staticmethod
    def _match_string(value: str, operator: str, pattern: str) -> bool:
        """Match string values."""
        operator = operator.lower()

        if operator == "contains":
            return pattern.lower() in value.lower()
        elif operator == "starts_with":
            return value.lower().startswith(pattern.lower())
        elif operator == "ends_with":
            return value.lower().endswith(pattern.lower())
        elif operator in ("equals", "=="):
            return value.lower() == pattern.lower()
        return False
