from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class LoginPolicy:
    domain: str
    service: str
    username_selector: str
    password_selector: str
    submit_selector: str
    login_url: Optional[str] = None
    post_login_selector: Optional[str] = None
    username_key: str = "USERNAME"
    password_key: str = "PASSWORD"


POLICIES: Dict[str, LoginPolicy] = {
    "example.com": LoginPolicy(
        domain="example.com",
        service="EXAMPLE_SITE",
        login_url="https://example.com/login",
        username_selector="input[name='username']",
        password_selector="input[name='password']",
        submit_selector="button[type='submit']",
        post_login_selector="body",
    ),
}