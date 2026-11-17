# NLWebAgent — Natural Language Web Testing Agent

[![CI](https://github.com/Tanner-Eischen/NLWebAgent/actions/workflows/ci.yml/badge.svg)](https://github.com/Tanner-Eischen/NLWebAgent/actions/workflows/ci.yml)

NLWebAgent uses screenshot and DOM context to turn natural-language instructions into Playwright actions. Explicit assertions check the final page independently of the model's completion signal. Automated sessions can be exported as Playwright TypeScript tests.

This is an alpha project. The regression suite covers control flow, data handling and generated source using mocks; it does not establish live model accuracy or reliability on arbitrary websites.

## Capabilities

| Capability | Behavior |
| --- | --- |
| Automation | Navigate, click, type, scroll, wait and extract with selector or coordinate actions |
| Verified tests | Execute a task, then evaluate repeatable `--expect` assertions against the final page |
| Page assertions | Numeric/string comparisons, visibility, existence and counts using a fixed grammar and DOM queries |
| Selector recovery | Ask a vision provider for coordinates when a selector cannot resolve |
| Automated recording | Save execution artifacts and export successful browser events to TypeScript |
| Providers | Ollama, Claude, and optional OpenAI/GLM adapters; optional Claude fallback |
| Authentication | Explicit domain policies, environment credentials, authenticated-page postconditions and storage reuse |

Assertions are deterministic DOM checks, not vision-based semantic judgments. Manual interaction recording is not implemented.

## Installation

Use Python 3.10 or later. Ollama is optional for local inference; browser execution requires Playwright's Chromium installation.

```bash
git clone https://github.com/Tanner-Eischen/NLWebAgent.git
cd NLWebAgent
python -m venv .venv
source .venv/bin/activate  # PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]" build
playwright install chromium
```

Install the optional SDK for your chosen provider:

```bash
pip install -e ".[openai]"
pip install -e ".[glm]"
# Or install both alongside development dependencies:
pip install -e ".[dev,openai,glm]"
```

The base installation includes the Ollama HTTP adapter and Anthropic SDK. Installing an adapter does not supply credentials or verify access to a particular hosted model.

## Configuration

Copy `.env.example` to `.env` and configure the provider you intend to use. For local inference:

```dotenv
MODEL_PROVIDER=ollama
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.2-vision:11b
FALLBACK_TO_CLAUDE=false
```

Download the configured model separately, for example `ollama pull llama3.2-vision:11b`.

| Setting | Purpose |
| --- | --- |
| `MODEL_PROVIDER` | Preferred explicit choice: `ollama`, `claude`, `openai` or `glm` |
| `USE_LOCAL_MODEL` | Legacy fallback when `MODEL_PROVIDER` is absent: `true` selects Ollama, `false` selects Claude |
| `CLAUDE_API_KEY` | Required for the Claude provider or enabled Claude fallback |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Credentials and model for the optional OpenAI provider |
| `ZHIPUAI_API_KEY`, `GLM_MODEL` | Credentials and model for the optional GLM provider |
| `FALLBACK_TO_CLAUDE` | Defaults to `false`; explicitly enable only when Claude fallback is wanted |
| `MODEL_TIMEOUT_SECONDS` | Deadline per provider call; an enabled fallback receives a separate deadline |
| `HEADLESS`, `RECORD_VIDEO` | Browser defaults; CLI browser options override them for that command |
| `REUSE_STORAGE_STATE`, `STORAGE_STATE_PATH` | Load/save browser state; loading state does not itself establish authentication |
| `AUTO_CHECKBOXES` | Defaults to `false`; prefer explicit task-directed checkbox actions |
| `PAUSE_ON_CAPTCHA` | Stop execution with a paused status when CAPTCHA detection triggers; no automatic resume workflow |

To enable remote fallback, set `FALLBACK_TO_CLAUDE=true` and provide a valid `CLAUDE_API_KEY`. Fallback can send the screenshot, task and DOM context to Claude. Provider names, credentials and SDK availability are validated before browser initialization; configuration errors do not silently switch providers.

## CLI usage

### Run an automation task

```bash
nlwa run --url https://example.com --task "Click the login button"
nlwa run --url https://shop.example.com --task "Add item to cart" --output ./results --headless --no-video
```

`run` reports whether the agent completed its action sequence. A model's `DONE` does not establish that a business outcome was verified. Use `test` with explicit expectations when the result will be used as a test verdict.

Common options are `--url`, `--task`, `--output` and `--max-steps`. All commands support `--headless/--headed`; `run` and `record` also support `--video/--no-video`. Omitting browser flags preserves the configured defaults.

### Verify a task's final state

```bash
nlwa test "Log in and open the dashboard" --url https://example.com/login --expect "#dashboard is visible"
nlwa test "Search for 'python'" --url https://example.com --expect "count(.result) >= 1" --expect "url contains 'search'" --output ./test-results
```

Each `--expect` uses the assertion grammar below. A test passes only when the agent completes successfully and every supplied final-page assertion passes. Reports contain the observed values and finalized artifact paths. `--fail-fast` stops evaluating expectations after the first failure.

Without `--expect`, the task can execute, but the test result is **unverified** and the command exits nonzero. Unsupported assertion expressions and page-query failures also fail rather than becoming passing negative checks. Successful verified tests exit 0; failed or unverified tests exit 1.

### Assert against a page

```bash
nlwa assert "price < 50" --url https://shop.example.com/product/123
nlwa assert "title contains 'Welcome'" --url https://example.com
nlwa assert "url starts with 'https'" --url https://example.com
nlwa assert "form is hidden" --selector "#login-form" --url https://example.com
nlwa assert "count(.item) >= 3" --url https://example.com/items
nlwa assert "#confirmation exists" --url https://example.com
```

Supported forms:

- Numeric comparisons: `<`, `<=`, `>`, `>=`, `==`, `=`.
- String comparisons: `contains`, `starts with`, `ends with`, `equals`.
- Visibility: `<element or selector> is visible` or `is hidden`.
- Counts: `count(<selector>) >= 3`.
- Existence: `<element or selector> exists`.

`--selector` overrides the target query. Numeric values support signed numbers, optional currency symbols, decimal points and comma thousands groups, such as `-$1,234.50`. Ambiguous ranges and decimal-comma formats are rejected. Use a selector targeting only the intended numeric value.

### Record an automated session and export it

```bash
nlwa record --url https://example.com --task "Search for 'test'" --output search.spec.ts
```

`--task` is required. Calling `record` without it fails before creating a browser or model. There is no manual interaction recorder. Exported tests use the fixed name `test_recorded` unless an explicit `--name` is supplied; names are not derived from task text.

Exports prefer successful executed browser events over proposed model actions, preserving resolved targets and coordinate units. Generated source requires the usual `@playwright/test` setup in the destination JavaScript/TypeScript project. Review the generated test and add explicit outcome assertions: extraction suggestions are comments and exporting a session is not independent verification of its intended result.

Typed values are redacted in saved recordings. When no explicit environment reference was used, the export reads a required variable such as `NLWA_INPUT_2`. The number comes from the executed event's position, including navigation events; consult the generated file for the exact names. Missing values fail replay instead of typing a redaction placeholder.

## Secrets and authentication

Use runtime references such as `${ENV:EXAMPLE_SITE_PASSWORD}` instead of literal secrets in tasks/actions. Keep the reference literal when invoking your shell; both PowerShell and Bash preserve it inside single quotes:

```bash
nlwa run --url https://example.com/login --task 'Fill the password with ${ENV:EXAMPLE_SITE_PASSWORD} and submit'
```

The environment value is resolved immediately before execution, registered for redaction, and represented by its reference in text artifacts. Explicit environment references are preserved in exported tests. Arbitrary typed values are redacted and require replay inputs as described above.

Text redaction does not sanitize screenshots, video, cookies or local storage. Treat these artifacts as sensitive and retain them only as needed.

### Login policies

`auth/policies.py` starts with an empty `POLICIES` mapping. Its `EXAMPLE_POLICY` is an inactive sample. Configure only your intended targets using `LoginPolicy` objects, for example:

```python
from auth.policies import LoginPolicy

POLICIES = {
    "example.com": LoginPolicy(
        domain="example.com",
        service="EXAMPLE_SITE",
        login_url="https://example.com/login",
        username_selector="#email",
        password_selector="#password",
        submit_selector="button[type='submit']",
        post_login_selector="[data-testid='authenticated-user']",
    ),
}
```

This policy reads `EXAMPLE_SITE_USERNAME` and `EXAMPLE_SITE_PASSWORD` from the environment. Choose a post-login selector visible only after successful authentication; `body`, `html` and similarly generic selectors do not prove login and are rejected. The manager checks the policy domain and authenticated state, stops after failed navigation, and checks the login destination before entering credentials.

When storage reuse is enabled, cookies/local storage are saved on close and loaded on later runs. Even an existing storage-state file must satisfy the authenticated-page postcondition before login can be skipped.

## Programmatic usage

```python
import asyncio

from agent.orchestrator import WebAutomationAgent
from browser.playwright_agent import BrowserController
from models.model_selector import ModelSelector


async def main():
    agent = WebAutomationAgent(
        model_selector=ModelSelector(),
        browser=BrowserController(headless=True, record_video=False),
    )
    try:
        await agent.initialize()
        result = await agent.execute_task(
            task_description="Search for 'python playwright'",
            start_url="https://example.com",
            max_steps=20,
        )
    finally:
        artifacts = await agent.close()
    result.update(artifacts)
    print(result["status"])


asyncio.run(main())
```

Use `AssertionEvaluator` against the final page before closing it when programmatic callers require a verified outcome.

## Actions

| Action | Text format |
| --- | --- |
| Click | `CLICK:<selector>` |
| Type | `TYPE:<selector>:<text>` |
| Extract | `EXTRACT:<selector>:<attribute>` |
| Coordinate click | `CLICK_AT:<x>:<y>` |
| Coordinate type | `TYPE_AT:<x>:<y>:<text>` |
| Navigate | `NAVIGATE:<url>` |
| Scroll | `SCROLL:<direction>:<amount>` |
| Wait | `WAIT:<seconds>` |
| Finish actions | `DONE` |
| Report error | `ERROR:<message>` |

Coordinates in the 0–1 interval use viewport proportions; exported browser events preserve their resolved pixel coordinates. Selector recovery is an attempt based on model output, not a guarantee that the recovered target is correct.

## Testing

Default test execution runs browser-free regressions and skips browser-backed suites. The former use fake pages and providers, so they need neither a running browser nor paid model inference:

```bash
python -m pytest tests/ -v
ruff check .
ruff format --check .
python -m build
```

Browser-backed fixture suites require explicit opt-in and installed Chromium:

```bash
playwright install chromium
python -m pytest tests/ --run-browser -v
```

CI runs the full suite with that opt-in on Python 3.10, 3.11 and 3.12, checks lint/formatting and builds the package. Browser tests use deterministic fake model responses; they do not establish live provider performance. Provider/account compatibility and end-to-end task accuracy require separate evaluation.

## Project structure

- `agent/`: action parsing and orchestration.
- `browser/`: Playwright controller and execution events.
- `models/`: provider adapters, deadlines and fallback.
- `auth/`: login policies, runtime secret references and text redaction.
- `cli/`: commands, assertion parser/evaluator and TypeScript export.
- `tests/`: browser-free regressions and opt-in browser fixtures.
- `config.py`: configuration and validation.
- `docs/audits/`: historical audit evidence and remediation notes.

## License

MIT License — see [LICENSE](LICENSE).
