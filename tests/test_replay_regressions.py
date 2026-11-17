import json
import shutil
import subprocess

import pytest

from agent.actions import ActionParseError, parse_action, parse_action_lenient
from cli.codegen.generator import generate_playwright_test


@pytest.mark.parametrize("parser", [parse_action, parse_action_lenient])
@pytest.mark.parametrize(
    ("raw", "selector", "payload"),
    [
        (
            "TYPE:input:nth-of-type(2):hello:world",
            "input:nth-of-type(2)",
            "hello:world",
        ),
        ("TYPE:input:focus:hello", "input:focus", "hello"),
        (
            'TYPE:input[data-url="https://x:y"]:hello',
            'input[data-url="https://x:y"]',
            "hello",
        ),
        (
            'TYPE:"input:unknown-custom-pseudo":hello',
            "input:unknown-custom-pseudo",
            "hello",
        ),
        (
            "TYPE:#input:do CLICK:#next then stop -> done",
            "#input",
            "do CLICK:#next then stop -> done",
        ),
    ],
)
async def test_selector_payload_is_not_corrupted(parser, raw, selector, payload):
    action = parser(raw)
    assert action.selector == selector
    assert action.text == payload


@pytest.mark.parametrize(
    "selector", ["li:nth-child(2)", 'a[href^="https:"]', r"#input\:field"]
)
def test_extract_preserves_selector(selector):
    action = parse_action(f"EXTRACT:{selector}:text")
    assert action.selector == selector
    assert action.attr == "text"


def test_json_action_preserves_exact_text_and_arbitrary_css():
    payload = {
        "type": "TYPE",
        "selector": "input:custom-pseudo",
        "text": " hello\nworld: -> done ",
    }
    assert parse_action(json.dumps(payload)).model_dump(mode="json") == payload


@pytest.mark.parametrize(
    "raw", ["WAIT:NaN", "WAIT:inf", "TYPE_AT:NaN:0.5:text", "TYPE_AT:inf:0.5:text"]
)
def test_reject_nonfinite_numbers(raw):
    with pytest.raises(ActionParseError):
        parse_action(raw)


def test_codegen_prefers_actual_successful_events_and_pixel_units():
    source = generate_playwright_test(
        {
            "url": "https://example.invalid/",
            "actions": [{"action": "CLICK:#missing", "status": "failed"}],
            "transcript": [
                {
                    "action": "click_at",
                    "x": 640,
                    "y": 360,
                    "coordinate_space": "pixels",
                    "viewport": {"width": 1280, "height": 720},
                }
            ],
        }
    )
    assert "#missing" not in source
    assert "page.mouse.click(640, 360)" in source
    assert '"width": 1280' in source


def test_legacy_codegen_skips_failed_actions_and_scales_normalized_coordinates():
    source = generate_playwright_test(
        {
            "actions": [
                {"action": "CLICK:#missing", "status": "failed"},
                {"action": "CLICK_AT:0.5:0.25", "status": "success"},
            ]
        }
    )
    assert "#missing" not in source
    assert "0.5 * page.viewportSize().width" in source
    assert "0.25 * page.viewportSize().height" in source


def test_codegen_redacted_inputs_require_environment_and_real_extraction_attribute():
    source = generate_playwright_test(
        {
            "transcript": [
                {
                    "action": "type",
                    "selector": "#password",
                    "text": "${ENV:LOGIN_PASSWORD}",
                },
                {
                    "action": "type_at",
                    "x": 2,
                    "y": 2,
                    "coordinate_space": "pixels",
                    "text": "[REDACTED]",
                },
                {"action": "extract", "selector": "a:nth-child(2)", "attr": "href"},
                {"action": "scroll", "direction": "left", "amount": 50},
            ]
        }
    )
    assert 'requiredEnv("LOGIN_PASSWORD")' in source
    assert 'requiredEnv("NLWA_INPUT_2")' in source
    assert '.getAttribute("href")' in source
    assert "[-50, 0]" in source
    assert "/.*" not in source


def test_codegen_preserves_pixel_coordinate_one():
    source = generate_playwright_test(
        {
            "transcript": [
                {"action": "click_at", "x": 1, "y": 1, "coordinate_space": "pixels"}
            ]
        }
    )
    assert "page.mouse.click(1, 1)" in source
    assert "viewportSize" not in source


def test_codegen_syntax_with_quotes_backslashes_newlines(tmp_path):
    if not shutil.which("node"):
        pytest.skip("Node is required for generated JavaScript syntax validation")
    source = generate_playwright_test(
        {
            "url": "https://example.invalid/it's?a=\\path",
            "transcript": [
                {"action": "click", "selector": '[data-label="customer\'s \\\\ path"]'},
                {"action": "type", "selector": "#q", "text": "${ENV:QUERY}"},
            ],
            "extractions": [
                {"selector": "#q", "attr": "text", "value": "line\n}); evil() //"}
            ],
        },
        test_name="customer's flow\nwith \\slashes",
    )
    path = tmp_path / "test.mjs"
    path.write_text(source, encoding="utf-8")
    checked = subprocess.run(
        ["node", "--check", str(path)], capture_output=True, text=True
    )
    assert checked.returncode == 0, checked.stderr


def test_codegen_cannot_silently_replay_redacted_target():
    with pytest.raises(ValueError, match="redacted"):
        generate_playwright_test(
            {"transcript": [{"action": "navigate", "url": "https://host/[REDACTED]"}]}
        )


@pytest.mark.parametrize(
    "raw",
    [
        'TYPE:"#input":active',
        'TYPE:selector="#input":active',
        "TYPE:#input:active user",
    ],
)
def test_quoted_selector_boundary_and_pseudo_named_input(raw):
    action = parse_action(raw)
    assert action.selector == "#input"
    assert action.text in {"active", "active user"}


def test_legacy_literal_inputs_never_embedded_and_keyboard_events_preserved():
    source = generate_playwright_test(
        {"actions": [{"action": "TYPE:#password:Old-Secret-123", "status": "success"}]}
    )
    assert "Old-Secret-123" not in source
    assert "requiredEnv(" in source
    assert 'page.fill("#password", "")' in source
    assert 'page.type("#password",' in source
    assert "delay: 50" in source
