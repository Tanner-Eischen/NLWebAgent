from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, Optional
from urllib.parse import urlparse

from auth.policies import POLICIES, LoginPolicy
from auth.redaction import SecretRedactor
from config import config

if TYPE_CHECKING:
    from browser.playwright_agent import BrowserController

logger = logging.getLogger(__name__)


class AuthManager:
    def __init__(
        self,
        policies: Optional[Dict[str, LoginPolicy]] = None,
        redactor: Optional[SecretRedactor] = None,
    ):
        self.policies = POLICIES if policies is None else policies
        self.redactor = redactor if redactor is not None else SecretRedactor()

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        if not domain:
            return ""
        domain = domain.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain.split(":")[0]

    def _find_policy(self, url: str) -> Optional[LoginPolicy]:
        if not url:
            return None
        domain = self._normalize_domain(urlparse(url).netloc)
        for key, policy in self.policies.items():
            normalized_key = self._normalize_domain(key)
            if domain == normalized_key or domain.endswith(f".{normalized_key}"):
                return policy
        return None

    def requires_login(self, url: str) -> bool:
        """Whether a configured policy requires verified login for this target."""
        return config.auth.enable_login_policies and self._find_policy(url) is not None

    @classmethod
    def _matches_domain(cls, url: str, domain: str) -> bool:
        actual = cls._normalize_domain(urlparse(url).hostname or "")
        expected = cls._normalize_domain(domain)
        return bool(expected) and (
            actual == expected or actual.endswith(f".{expected}")
        )

    @staticmethod
    def _origin(url: str) -> tuple:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Login destination must be an HTTP(S) URL")
        return (
            parsed.scheme,
            parsed.hostname.lower(),
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )

    @staticmethod
    def _has_postcondition(policy: LoginPolicy) -> bool:
        selector = (policy.post_login_selector or "").strip().lower()
        # These only prove that a document exists, not that login succeeded.
        return bool(selector) and all(
            part.strip() not in {"body", "html", "*", ":root", "html body"}
            for part in selector.split(",")
        )

    async def _is_authenticated(self, browser, policy: LoginPolicy) -> bool:
        if not self._matches_domain(browser.page.url, policy.domain):
            return False
        return await browser.page.locator(policy.post_login_selector).first.is_visible()

    async def ensure_logged_in(
        self, browser: BrowserController, url: Optional[str] = None
    ) -> bool:
        if not config.auth.enable_login_policies:
            return False

        current_url = url or (browser.page.url if browser and browser.page else "")
        policy = self._find_policy(current_url)
        if not policy:
            return False

        if not browser or not browser.page or not self._has_postcondition(policy):
            logger.warning("Login policy requires a specific authenticated selector")
            return False

        try:
            if await self._is_authenticated(browser, policy):
                return True

            destination = policy.login_url or current_url
            expected_origin = self._origin(destination)
            if policy.login_url and not await browser.navigate(policy.login_url):
                logger.warning("Login navigation failed; credentials were not entered")
                return False
            if self._origin(browser.page.url) != expected_origin:
                logger.warning(
                    "Unexpected login destination; credentials were not entered"
                )
                return False

            username = config.get_credential(policy.service, policy.username_key)
            password = config.get_credential(policy.service, policy.password_key)
            for key, value in (
                (policy.username_key, username),
                (policy.password_key, password),
            ):
                name = f"{policy.service.upper()}_{key.upper()}"
                self.redactor.add(value, replacement=f"${{ENV:{name}}}")

            if not await browser.type_text(policy.username_selector, username):
                return False
            if self._origin(browser.page.url) != expected_origin:
                return False
            if not await browser.type_text(policy.password_selector, password):
                return False
            if self._origin(browser.page.url) != expected_origin:
                return False
            if not await browser.click(policy.submit_selector):
                return False

            await browser.page.wait_for_selector(
                policy.post_login_selector,
                state="visible",
                timeout=config.browser.timeout_seconds * 1000,
            )
            authenticated = await self._is_authenticated(browser, policy)
            if authenticated:
                logger.info("Login postcondition verified")
            return authenticated
        except Exception:
            # Browser/credential exceptions can include entered values or URLs.
            logger.warning("Login could not be verified")
            return False
