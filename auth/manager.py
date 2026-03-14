import logging
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

from auth.policies import LoginPolicy, POLICIES
from browser.playwright_agent import BrowserController
from config import config

logger = logging.getLogger(__name__)


class AuthManager:
    def __init__(self, policies: Optional[Dict[str, LoginPolicy]] = None):
        self.policies = policies or POLICIES

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

    async def ensure_logged_in(
        self, browser: BrowserController, url: Optional[str] = None
    ) -> bool:
        if not config.auth.enable_login_policies:
            return False

        if config.browser.reuse_storage_state and config.browser.storage_state_path:
            if Path(config.browser.storage_state_path).exists():
                logger.info("Storage state present; skipping login policy")
                return True

        current_url = url or (browser.page.url if browser and browser.page else "")
        policy = self._find_policy(current_url)
        if not policy:
            return False

        try:
            username = config.get_credential(policy.service, policy.username_key)
            password = config.get_credential(policy.service, policy.password_key)
        except Exception as e:
            logger.info(f"Credentials missing for {policy.service}: {e}")
            return False

        if policy.login_url:
            await browser.navigate(policy.login_url)

        ok_user = await browser.type_text(policy.username_selector, username)
        ok_pass = await browser.type_text(policy.password_selector, password)
        ok_submit = await browser.click(policy.submit_selector)

        if not (ok_user and ok_pass and ok_submit):
            logger.warning("Login interaction failed")
            return False

        if policy.post_login_selector:
            try:
                await browser.page.wait_for_selector(
                    policy.post_login_selector,
                    timeout=config.browser.timeout_seconds * 1000,
                )
            except Exception as e:
                logger.warning(f"Login wait failed: {e}")
                return False

        logger.info(f"Login succeeded for {policy.service}")
        return True
