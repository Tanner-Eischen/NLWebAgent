import unittest

from agent.actions import ActionParseError, ActionType, parse_action, parse_action_lenient


class ActionParsingTests(unittest.TestCase):
    def test_valid_actions(self):
        cases = [
            ("CLICK:#submit", ActionType.CLICK),
            ("CLICK_AT:100:200", ActionType.CLICK_AT),
            ("TYPE:#input:hello", ActionType.TYPE),
            ("TYPE_AT:100:200:hello", ActionType.TYPE_AT),
            ("NAVIGATE:https://example.com", ActionType.NAVIGATE),
            ("SCROLL:down:120", ActionType.SCROLL),
            ("WAIT:1.5", ActionType.WAIT),
            ("EXTRACT:.title:text", ActionType.EXTRACT),
            ("DONE", ActionType.DONE),
            ("ERROR:Something went wrong", ActionType.ERROR),
            ("DONE:", ActionType.DONE),
            ("DONE -> success", ActionType.DONE),
        ]

        for raw, expected_type in cases:
            with self.subTest(raw=raw):
                action = parse_action(raw)
                self.assertEqual(action.type, expected_type)

    def test_type_allows_colons_in_text(self):
        action = parse_action("TYPE:#input:hello:world")
        self.assertEqual(action.type, ActionType.TYPE)
        self.assertEqual(action.text, "hello:world")

    def test_normalizes_selector_and_text_fields(self):
        action = parse_action('CLICK:selector="input#q"')
        self.assertEqual(action.selector, "input#q")

        action = parse_action('TYPE:selector="input#q":text="hello world"')
        self.assertEqual(action.selector, "input#q")
        self.assertEqual(action.text, "hello world")

        action = parse_action('NAVIGATE:url="https://example.com"')
        self.assertEqual(action.url, "https://example.com")

        action = parse_action('EXTRACT:selector=\"#title\":attr=\"href\"')
        self.assertEqual(action.selector, "#title")
        self.assertEqual(action.attr, "href")

        action = parse_action("CLICK_AT:x=120:y=240")
        self.assertEqual(action.x, 120)
        self.assertEqual(action.y, 240)

        action = parse_action('TYPE_AT:x=10:y=20:text=\"hello\"')
        self.assertEqual(action.x, 10)
        self.assertEqual(action.y, 20)
        self.assertEqual(action.text, "hello")

        action = parse_action("CLICK_AT:0.5:0.25")
        self.assertEqual(action.x, 0.5)
        self.assertEqual(action.y, 0.25)

        action = parse_action('CLICK:input[placeholder="Search"]:Search for stuff')
        self.assertEqual(action.selector, 'input[placeholder="Search"]')

        action = parse_action("TYPE:<textarea[aria-label='Search']>:hello")
        self.assertEqual(action.selector, "textarea[aria-label='Search']")

    def test_multiline_response_extracts_action(self):
        action = parse_action("Some note\nCLICK:#search\nMore text")
        self.assertEqual(action.type, ActionType.CLICK)
        self.assertEqual(action.selector, "#search")

    def test_action_prefix_stripped(self):
        action = parse_action("The next action is: CLICK:#search")
        self.assertEqual(action.type, ActionType.CLICK)
        self.assertEqual(action.selector, "#search")

    def test_strip_result_suffix(self):
        action = parse_action("NAVIGATE:https://example.com -> success")
        self.assertEqual(action.type, ActionType.NAVIGATE)
        self.assertEqual(action.url, "https://example.com")

    def test_click_at_with_trailing_text(self):
        action = parse_action("CLICK_AT:0.5:0.5:extra text")
        self.assertEqual(action.type, ActionType.CLICK_AT)
        self.assertEqual(action.x, 0.5)
        self.assertEqual(action.y, 0.5)

    def test_markdown_wrapped_action(self):
        action = parse_action("**CLICK_AT:0.25:0.75**")
        self.assertEqual(action.type, ActionType.CLICK_AT)
        self.assertEqual(action.x, 0.25)
        self.assertEqual(action.y, 0.75)

    def test_multiple_actions_raise(self):
        with self.assertRaises(ActionParseError):
            parse_action("NAVIGATE:https://example.com\nDONE")

    def test_lenient_parsing_picks_first_action(self):
        action = parse_action_lenient("NAVIGATE:https://example.com\nDONE")
        self.assertEqual(action.type, ActionType.NAVIGATE)

    def test_lenient_ignores_prompt_echo(self):
        raw = """Return exactly ONE line using one of these formats:
CLICK:<css selector>
DONE
NAVIGATE:https://example.com
"""
        action = parse_action_lenient(raw)
        self.assertEqual(action.type, ActionType.NAVIGATE)

    def test_lenient_extracts_from_or_list(self):
        raw = "CLICK:#a\nOR\nTYPE:#b:hi\nOR\nDONE"
        action = parse_action_lenient(raw)
        self.assertEqual(action.type, ActionType.CLICK)

    def test_invalid_actions_raise(self):
        cases = [
            "",
            "TYPE:",
            "TYPE:#input",
            "CLICK:",
            "NAVIGATE:",
            "SCROLL:down",
            "SCROLL:sideways:10",
            "WAIT:abc",
            "EXTRACT:.title",
            "ERROR:",
            "CLICK:selector | TYPE:selector:text",
            "CLICK:" + ("div > " * 10) + "span",
        ]

        for raw in cases:
            with self.subTest(raw=raw):
                with self.assertRaises(ActionParseError):
                    parse_action(raw)

    def test_unsupported_action_returns_error(self):
        with self.assertRaises(ActionParseError):
            parse_action("FLY:now")


if __name__ == "__main__":
    unittest.main()
