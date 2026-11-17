# NLWebAgent capability and reliability audit

Historical baseline: the fixes and current verification results are recorded in [REMEDIATION.md](REMEDIATION.md). The diagnostic scripts below reproduce the original revision's defects and are not regression gates for the corrected code.

Audit date: November 16, 2026. Repository: https://github.com/Tanner-Eischen/NLWebAgent

Audited revision: `5ea12fd6be8a608463701081296d1236933ae1fa` (`main`, September 10, 2026).
Clone: `C:\Users\tanne\projects\NLWebAgent`.

NLWebAgent has a useful alpha-stage architecture for model-guided browser actions, but its test verdicts and generated replay files are not yet reliable enough to use as release gates. The most urgent work is correctness: successful CLI operations return failure, some assertions pass on execution errors, and several advertised recovery/recording paths are incomplete. This conclusion is based on source review and browser-free reproductions, not a live evaluation of its models or browser performance.

Only this audit directory was added. Production code was not changed; no commit or push was made. No browser/UI was opened or inspected, and no real model inference or authentication was performed.

## Current capabilities

| Area | Implemented | Practical limit |
| --- | --- | --- |
| CLI | `nlwa run`, `test`, `assert`, `record`; JSON/Markdown results | Successful command exit handling is broken; several options are ineffective |
| Agent loop | Screenshot and DOM context, recent action history, typed action parsing, retries, per-call timeout, step limit | Model `DONE` is accepted as success; no independent outcome verification |
| Browser actions | Chromium navigation, selector/coordinate click and typing, four-direction scroll, wait, extraction | No exposed action for keypress, select option, uploads, tabs, frames, downloads or dialogs; navigation is blocked after initial load |
| Providers | Ollama, Anthropic, OpenAI and GLM adapter implementations | OpenAI/GLM SDKs are missing from installation metadata; live compatibility and quality untested |
| Fallback | Claude fallback after ordinary provider exceptions | Timeout cancellation bypasses fallback; GLM synchronous calls block the event loop |
| Assertions | Fixed grammar for numeric/string comparisons, visibility, counts and existence | DOM-based selector heuristics, not vision-based semantic reasoning; error handling can create false passes |
| Recording | Screenshots, optional video, browser transcript, automated action history | Manual interaction capture is absent; video is not a structured action recording |
| Code generation | Basic Playwright TypeScript conversion and commented extraction suggestions | Replay coordinates, failed actions, escaping and attribute extraction are unreliable; executable default URL assertion is effectively vacuous |
| Authentication | Domain policies, environment credentials, optional post-login selector, persisted browser state | Only a sample policy ships; stored-state existence is incorrectly treated as authenticated status |
| Quality infrastructure | Ruff lint/format, package build, deterministic parser and browser fixture tests, CI Python 3.10–3.12 matrix | CLI, assertions, codegen and providers lack dedicated existing coverage; several workflow assertions check bookkeeping rather than page outcomes |

## Highest-priority defects

P1 means fix before treating the tool as a dependable test runner or using sensitive sessions. P2 means a significant functional defect. “Reproduced” below means a local pure-function/mock reproduction; it does not imply live browser verification.

### 1. P1 — Success is converted to process failure in every operational CLI command

Sources: `cli/commands/run.py:112–121`, `test.py:133–144`, `assert_cmd.py:94–103`, `record.py:164–171`.

The commands raise `typer.Exit(0)` inside a `try` whose `except Exception` catches that same exit and raises exit code 1. The assertion probe confirmed a passing evaluator still exits 1. The other three commands have the same control-flow defect. This makes shell/CI callers see failures even when reports show success.

Fix: move normal exit handling outside the exception handler or explicitly re-raise `typer.Exit`. Add CLI-runner tests for success, assertion failure and runtime failure.

### 2. P1 — Natural-language test passes are not evidence of the requested result

Sources: `cli/commands/test.py:149–210`; `agent/orchestrator.py:240–244`.

The orchestrator accepts `DONE`, and the test command mainly checks this status, action-text keywords and non-null extraction values. The probe confirmed “Verify checkout completed” passes with success status and no actions or extractions. Login checks look for username/password substrings, not authenticated state, and do not check whether those individual actions succeeded.

Fix: separate “agent finished” from “test passed.” Require explicit postconditions against the final page and save the observed evidence. Report an unverified outcome when no meaningful assertion exists.

### 3. P1 — Broken page queries can pass negative assertions

Source: `cli/assertions/evaluator.py:213–227`.

Visibility/count helpers catch every exception and return `False`/`0`. Both a hidden-element assertion and `count(.item) == 0` passed with no error when a mocked locator raised “page closed or invalid selector.” This hides infrastructure and selector failures as successful tests.

Fix: preserve query failures and let `evaluate()` return an error result; distinguish a valid zero-match query from an operation that could not execute.

### 4. P1 — Quoted tasks can skip coordinate clicks while reporting success

Sources: `agent/orchestrator.py:189–209`, `462–476`.

For a task containing quoted text, `_should_auto_type` intercepts `CLICK_AT` before executing it. It marks the action successful and tries to type at a previous successful click. With no previous click, nothing happens. The probe sent `CLICK_AT:0.5:0.5` then `DONE` for `Search for 'query'`: status was success, the first action was recorded as success, and actual mock click calls were zero. The `continue` also bypasses the usual retry increment and screenshot refresh.

Fix: remove this task-text heuristic or make it an explicit action sequence that executes and records the click before typing. Completion must still require the task's postcondition.

### 5. P1 — Authentication state and credential handling need correction

Sources: `auth/manager.py:42–45,59–64`; `browser/playwright_agent.py:623–627`; `agent/orchestrator.py:158–164`; report serialization in `cli/commands/run.py:99–101`.

- Any existing storage-state file skips login policies for every target, without checking cookies, domain, expiry or authenticated UI. An empty cookies/origins file reproduced `login_result=True` with zero login calls. Browser close saves state even after anonymous sessions.
- Failed navigation to the configured login URL is ignored. The probe returned `False` from navigation, but credential entry and submit still ran and login returned `True`. This can enter credentials on the page left open after a navigation failure. This subissue is P2 individually.
- Raw model actions retain typed secrets in task results and are logged when info logging is enabled; reports serialize those actions without redaction. A synthetic password probe confirmed retention. Browser transcripts omit typed text, but the agent's separate action history does not. No real secrets were inspected or tested.

Fix: verify authenticated state per policy/domain, abort after failed login navigation, require a meaningful post-login condition, and use secret references plus redacted reporting rather than raw credential text. Document storage/report sensitivity.

## Other confirmed functional defects

| ID | Priority | Finding, evidence and fix |
| --- | --- | --- |
| 6 | P2 | **Direct vision self-healing never calls the provider.** `agent/orchestrator.py:400` uses `self.model_selector.model`, but `ModelSelector` exposes provider fields and `get_primary_model()`, not `.model`. The probe returned no coordinates and recorded zero vision calls. Route analysis through a supported selector API. The separate error-hint retry can still request coordinate actions, so not every recovery mechanism is broken. |
| 7 | P2 | **CLI browser flags are ineffective.** Commands mutate environment variables after the `config` singleton is loaded. The probe requested headless mode and observed the old config value. Pass explicit settings into components; cover `--headless` and `--no-video`. Sources: `cli/commands/run.py:70–71`, `test.py:67`, `assert_cmd.py:67`, `record.py:77–78`. |
| 8 | P2 | **Assertion target override is unused.** `assert_cmd.py:75–78` ignores `--selector`; the probe supplied `#target` but the evaluator received generic `button`. Apply the override to the evaluator's actual query path. |
| 9 | P2 | **Manual record mode does not capture interactions.** `record.py:114–130` records the initial navigation and sleeps; no interaction listeners are installed. `generator.py:30` ignores the transcript. Static finding. Implement event capture or describe the feature as automated-session export until manual capture exists. |
| 10 | P2 | **Generated tests do not faithfully replay executed actions.** `generator.py:46–48,102–125` includes failed actions and emits normalized coordinates as literal pixels. The probe generated `mouse.click(0.5, 0.5)` for a viewport-center click and included `#missing` from a failed action. Use a canonical execution log with resolved targets, successful actions and explicit coordinate units. `EXTRACT` additionally ignores its requested attribute at lines 150–154. |
| 11 | P2 | **Generated strings can be syntactically invalid or change meaning.** `generator.py:39,43,131,163–171` lacks consistent escaping. `customer's flow` produces invalid quoted JavaScript; backslashes are not correctly serialized. Use JSON string serialization for all names, selectors, text and URLs, then syntax-check exports without opening a browser. |
| 12 | P2 | **Numeric extraction loses minus signs.** `evaluator.py:196–199` parses `-$20` as positive `20`; the probe incorrectly passed `price > 0`. Define signed/currency/locale handling and reject ambiguous values. |
| 13 | P2 | **Primary timeouts prevent Claude fallback; GLM can ignore timeout entirely.** The orchestrator wraps the entire fallback operation in `wait_for` (`orchestrator.py:126–136`), cancelling it before the selector catches an ordinary exception (`model_selector.py:135–149`). A delayed fake primary timed out with zero fallback calls. GLM's synchronous SDK calls inside async methods (`glm_model.py:49,69,126`) completed after about 0.10 seconds despite a 0.01-second deadline. Apply independent provider deadlines and use async transport or a bounded worker with network timeout. |
| 14 | P2 | **Provider installation/configuration is inconsistent.** Neither `openai` nor `zhipuai` is declared in `pyproject.toml:34–44` or offered through extras; both are absent in the clean audit environment. `USE_LOCAL_MODEL=false` is loaded but does not affect selection; the probe still initialized Ollama. Add provider extras, reconcile configuration semantics, validate before creating a browser, and consolidate `requirements.txt` with package metadata. |
| 15 | P2 | **Action parsing corrupts selectors containing colons.** `agent/actions.py:258–263,290–296` and corresponding lenient branches split `TYPE`/`EXTRACT` on `:` without respecting selector syntax. The probe parsed `TYPE:input:nth-of-type(2):hello` into selector `input` and text `nth-of-type(2):hello`. Use a structured action schema; retain a carefully tested compatibility parser if needed. |
| 16 | P2 | **All later model navigation is blocked, even to a different URL.** `orchestrator.py:211–224` disables `NAVIGATE` once the starting URL was loaded. The probe failed a request to navigate to a distinct second URL. Replace the global ban with bounded duplicate-navigation detection. |

## Additional gaps and improvements

- `AUTO_CHECKBOXES=true` automatically checks the first available checkbox each step, irrespective of the task. This can alter forms unrelated to the requested action. Disable this default and make checkbox changes explicit model actions. CAPTCHA detection is nested inside the checkbox option (`orchestrator.py:92–108`); the probe confirmed turning off auto-checkboxes also turns off CAPTCHA detection even with pause enabled. Separate the settings. The paused state currently ends execution rather than implementing a resume workflow.
- The recording-artifact test fake does not accept the `dom_context` keyword passed by the orchestrator (`tests/test_recording_artifacts.py:25`, `orchestrator.py:127–132`). The signature mismatch is confirmed without running a browser. Its test checks screenshots/video existence but never asserts task success, allowing it to miss an orchestration error.
- `.github/workflows/ci.yml:32–43` invokes individual suites and omits `tests/test_retry_behavior.py`. Several fixture workflows assert action count/status, not actual final DOM state. Full-suite runs also share mutable configuration via module imports and environment `setdefault`, making recording settings sensitive to test collection order.
- `run` saves results before `agent.close()` appends finalized video/transcript metadata. Close first, merge artifacts, then persist the final result; retain error-safe cleanup.
- `ModelSelector.close()` only closes Ollama. Add consistent client lifecycle management and a shared model protocol including action selection and cleanup.
- `Config.validate_config()` has no callers. Centralize configuration validation and provider error messages. `--fail-fast` is accepted but unused.
- README authentication setup uses `LOGIN_POLICIES` dictionaries, while implementation expects `POLICIES` containing `LoginPolicy` objects with `service` and credential keys. Update examples and remove unsupported capability claims.
- Avoid solving scale concerns before correctness. After fixes, measure success on held-out local tasks, action counts, retries, model latency and cost. Add screenshot/DOM caching only after measuring redundancy.

## Recommended implementation order

1. **Trustworthy results:** fix CLI exits, fail closed on query errors, separate completion from assertions, remove skipped-click behavior, repair auth-state checks and secret handling. Add browser-free regression tests for these defects.
2. **Faithful execution and replay:** create a structured action/execution-event schema shared by parsing, execution, transcripts and codegen. Record actual resolved actions and artifact metadata, support explicit coordinate units, and add export syntax checks. Implement manual event capture separately.
3. **Provider/config reliability:** explicit config injection, optional provider dependencies, per-provider timeout/fallback tests, asynchronous GLM transport, client cleanup and early validation.
4. **Evidence and usability:** run all test modules in CI, assert final page states, make test configuration isolated, correct docs, then build a measured fixture benchmark across providers. Live/browser evaluation remains a separate verification step under the repository's access rules.

Automate the repeated audit workflow as a browser-free CI job covering CLI outcomes, assertion failure handling, model adapters with fake transports, and codegen syntax. The diagnostic scripts here intentionally confirm current bugs; convert them into tests for corrected behavior rather than adding them unchanged as regression gates.

## Verification evidence and limits

Local environment: isolated `.venv`, Python 3.14.0, dependencies installed from `.[dev]` plus `build`. Python 3.10–3.12 were not rerun locally.

| Check | Result |
| --- | --- |
| Existing browser-free pytest selection | 15 passed: `tests/test_action_parsing.py` and `tests/test_fixture_workflows.py::test_action_parsing` |
| Ruff lint | Passed |
| Ruff formatting | Passed before and after adding audit probes |
| `python -m build` | Built both sdist and wheel successfully |
| `nlwa --help` | Passed; all four operational commands exposed |
| Targeted diagnostic scripts | CLI: 8 cases; model/auth: 6 observations; orchestration: 7 groups confirmed |
| GitHub CI for exact audited SHA | Reported success: https://github.com/Tanner-Eischen/NLWebAgent/actions/runs/34482844271 |
| Browser-backed suites, generated browser replays, live auth/providers | Not run under the no-UI restriction; no real-world performance claim |

The green historical CI result is not evidence that the defects above are absent. Mocks establish control-flow and data-handling defects; they do not establish page rendering, provider model availability or end-to-end task success.

Reproduce from the repository root in PowerShell:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_action_parsing.py tests/test_fixture_workflows.py::test_action_parsing -q
.venv\Scripts\python.exe docs/audits/2026-11-16/cli_probes.py
.venv\Scripts\python.exe docs/audits/2026-11-16/model_auth_probes.py
.venv\Scripts\python.exe docs/audits/2026-11-16/orchestration_probes.py
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .
.venv\Scripts\python.exe -m build
```

Saved outputs are `cli_probe_results.txt`, `model_auth_probe_results.txt` and `orchestration_probe_results.txt` in this directory. These scripts use synthetic inputs and mocks; they do not launch browsers or call live models.
