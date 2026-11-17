"""Keep browser execution explicit and isolate mutable browser settings."""

import pytest

from config import config


def pytest_addoption(parser):
    parser.addoption(
        "--run-browser", action="store_true", help="Run browser-backed tests"
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "browser: launches a real Playwright browser")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-browser"):
        for item in items:
            if item.get_closest_marker("browser"):
                item.add_marker(
                    pytest.mark.skip(reason="requires explicit --run-browser")
                )


@pytest.fixture(autouse=True)
def isolated_browser_settings(request, monkeypatch, tmp_path):
    if not request.node.get_closest_marker("browser"):
        return
    monkeypatch.setattr(config.browser, "headless", True)
    monkeypatch.setattr(config.browser, "record_video", False)
    monkeypatch.setattr(config.browser, "reuse_storage_state", False)
    monkeypatch.setattr(config.browser, "timeout_seconds", 2)
    monkeypatch.setattr(config.agent, "auto_checkboxes", False)
    monkeypatch.setattr(config.agent, "pause_on_captcha", False)
    for field in ("screenshot_dir", "video_dir", "transcript_dir"):
        path = tmp_path / field
        path.mkdir()
        monkeypatch.setattr(config.browser, field, str(path))
    monkeypatch.setattr(
        config.browser, "storage_state_path", str(tmp_path / "state.json")
    )
