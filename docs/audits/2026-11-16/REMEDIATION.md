# Audit remediation — November 16, 2026

Implemented locally on the checkout originally audited at `5ea12fd`. No commit or push was made. The original audit and diagnostic outputs remain historical evidence; its diagnostic scripts intentionally assert old bugs and are not tests for the corrected implementation.

## Audit disposition

| Audit ID | Change | Regression coverage |
| --- | --- | --- |
| 1 | CLI exits occur outside broad exception handling; success remains exit 0 and failures remain nonzero. Cleanup precedes final report persistence. | `tests/test_cli_regressions.py` |
| 2 | `nlwa test` evaluates repeatable `--expect` assertions on the final page. Model completion alone produces an unverified, nonzero test result. Execution status and outcome verification are separate. | CLI and orchestrator regressions |
| 3 | Visibility/count/existence query errors propagate to failed assertion results rather than hidden/zero successes. | `tests/test_assertion_regressions.py` |
| 4 | Removed quoted-task auto-typing and synthetic click success. Every requested coordinate action executes explicitly. | `tests/test_orchestrator_regressions.py` |
| 5 | Authentication checks a specific visible postcondition and matching domain. Failed navigation, unexpected login origin, failed form steps and failed postconditions stop authentication. Typed data is redacted; explicit environment references resolve immediately before typing. Reports, histories, transcripts and exception messages share redaction. | Auth, browser, CLI and orchestrator regressions |
| 6 | Vision recovery uses the supported model-selector analysis API, with independent provider timeout/fallback handling. | Model and orchestrator regressions |
| 7 | Browser settings use constructor overrides. Omitted CLI options preserve configured defaults; explicit headless/headed and video choices override them. | Browser and CLI regressions |
| 8 | Assertion selector overrides reach the actual numeric, string, count, visibility and existence query paths. | Assertion and CLI regressions |
| 9 | Removed the misleading manual-recording path. `record` requires `--task` and rejects missing tasks before initializing models or browsers. Manual event capture is explicitly unsupported, not claimed implemented. | CLI regressions |
| 10 | Exports prefer successful browser execution events, including resolved selectors and pixel coordinate metadata. Legacy normalized coordinates scale to the viewport. Typing replay preserves clear-and-type behavior, scroll supports all directions and extraction respects the requested attribute. | `tests/test_replay_regressions.py` |
| 11 | Generated names, URLs, selectors and values use JSON serialization. Typed literals from older recordings become required environment inputs. Generated JavaScript is syntax-checked with Node in a regression test. | Replay regressions |
| 12 | Numeric extraction preserves signs/currency and rejects ambiguous number formats rather than silently changing values. | Assertion regressions |
| 13 | Primary and Claude fallback calls have separate deadlines. GLM's synchronous SDK calls run off the event loop with SDK transport timeout and retries disabled. Caller cancellation does not start fallback. | `tests/test_model_regressions.py` |
| 14 | Added OpenAI/GLM installation extras and explicit setup errors. Legacy provider selection works unless overridden by `MODEL_PROVIDER`; fallback is opt-in. Requirements now use the package metadata as their source. | Model/config regressions and wheel installation |
| 15 | Added structured JSON action parsing and a shared compatibility parser for quoted selectors, CSS pseudo-classes, attribute values and escaped colons. Strict and lenient parsing use the same implementation. | Original parser tests and replay/parser regressions |
| 16 | Distinct subsequent URLs are allowed; navigation to the current URL is rejected with bounded retries. | Orchestrator regressions |

Additional fixes include: automatic checkboxes default off; CAPTCHA checks are independent of checkbox settings; explicit model `ERROR` is terminal; all provider clients are closed; recording's default name no longer derives from potentially sensitive task text; the artifact-test fake accepts DOM context and checks task success; browser tests use isolated settings; CI includes retry coverage; README examples match the actual API and configuration.

## Changed usage

```powershell
nlwa test "Login and open the dashboard" --url https://example.com/login --expect "#dashboard is visible"
nlwa test "Search for products" --url https://example.com --expect "count(.result) >= 1" --expect "#error is hidden"
nlwa record --url https://example.com --task 'Fill the password using ${ENV:LOGIN_PASSWORD}' --output login.spec.ts
```

- `run` reports whether the agent completed; it does not certify the intended outcome. `test` requires explicit outcome assertions for a verified pass.
- `record` exports automated sessions only. Supply `--task`; manual capture is a future feature.
- Preserve literal `${ENV:NAME}` references in task strings using shell quoting. They resolve at execution time and remain references in replay output. Other typed values are masked and replay requires the corresponding `NLWA_INPUT_N` environment variable. `N` is the execution-event index, including navigation events.
- Use `--headless` / `--headed`, and `--video` / `--no-video` where supported. Omitted settings inherit configuration.
- Claude fallback defaults to disabled. Enable it explicitly with credentials if wanted.
- Default authentication policies are empty. Configure an actual `LoginPolicy` with a meaningful authenticated-page selector; `EXAMPLE_POLICY` is an inactive illustration.

## Verification

| Check | Result |
| --- | --- |
| Full default suite on Python 3.14.0 | **176 passed, 8 skipped** |
| Full default suite on Python 3.10.11 | **176 passed, 8 skipped** |
| New regression cases | **161**, across seven new regression test modules |
| Ruff lint and formatting | Passed |
| `git diff --check` | Passed |
| Python compilation | Passed |
| Generated JavaScript syntax | Passed using `node --check` without running a browser |
| Python package build | sdist and wheel built successfully |
| Wheel contents | Python source compared with the final checkout, normalizing line endings; no mismatches |
| Clean wheel install on Python 3.10 | Installed successfully; imports and `nlwa --help` passed from outside the repository import path |

Run the browser-free regression suite with:

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .
.venv\Scripts\python.exe -m build
```

Browser-backed tests are marked `browser` and require explicit `--run-browser`. CI is configured to run both the browser-free suite and the browser fixtures/retries. No new CI run has been observed because these changes have not been pushed.

## Verification limits

No browser/platform UI was opened, inspected or operated. The eight real-browser tests were deliberately skipped, and real model inference, real login flows, visual artifacts and generated browser replay remain unverified. Mock-based tests establish control flow, data handling and code generation; they do not establish real-world model accuracy.

GLM cancellation cannot forcibly terminate an SDK worker thread already in progress; the SDK transport timeout bounds its network wait. Action text redaction does not scrub pixels from screenshots/videos or protect browser storage files; those artifacts remain sensitive. The legacy colon action syntax has inherent ambiguities for arbitrary text; structured JSON actions or explicitly quoted selectors are preferred.
