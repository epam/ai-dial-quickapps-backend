---
name: quickapps-write-integration-test
description: Use when adding an integration test for a QuickApps 2.0 feature or design doc (docs/designs/), especially when the test must drive a real agent end-to-end, needs new REST/MCP test tooling, or you're unsure which model to run or whether to commit cache files.
---

# Writing a QuickApps integration test

Turn a feature (often a design doc under `docs/designs/`) into a deterministic end-to-end test in `src/tests/integration_tests/`.

**Harness mechanics (TstCase API, decorator params, cache files, config sets, similarity thresholds, ToolNames, attachment checks) are already documented in `.claude/rules/integration-testing.md` — it auto-loads when you work in the test dir. READ IT FIRST. This skill covers the workflow and the non-obvious traps that doc does not foreground.**

## Workflow

1. **Read the design doc; list use cases.** Separate what is genuinely end-to-end (agent calls tools, data flows) from config-gating / fail-open / pure-logic branches — those belong in **unit tests**, not here. Don't try to drive every branch through a live agent.
2. **Find the assertable signal.** An integration test can only check: which tools the agent called (+ their args), the final answer text, and response attachments. Pick a use case whose success is provable through those.
3. **Make the test self-proving.** Design it so the assertion can ONLY pass if the feature worked. Best lever: embed a unique marker (e.g. `SECRET ACCESS CODE: ZX-9981-QUASAR`) that the agent can reach *only via the feature's path*, then assert the marker in the answer. If the feature silently no-ops, the agent can't produce the marker and the test fails.
4. **Add test tooling if needed** (see below) to trigger the behavior (e.g. a REST endpoint returning a >40KB body to trigger offload).
5. **Write the test** following the rules-doc pattern (`@pytest.mark.integration` + `@e2e_test` + `TstCase`, empty body).
6. **Verify live and iterate** (see Verification). Tune the prompt until stable.
7. `make format` then `make lint`.

## Critical traps (these cost real time this session)

### Caching only covers tool-DEPLOYMENT calls — the orchestrator runs LIVE
The cache middleware records only DIAL-deployment tool calls (RAG, image-gen, web-search). The orchestrator/agent model (every entry in `AGENT_MODELS` in `cache/cache_middleware.py`, e.g. `gpt-5.2`) is **always proxied live**. Consequences:
- A flow that calls only REST / internal / MCP tools makes **zero cacheable calls** → there are **no `.response` files to generate or commit**. Don't run `REFRESH=TRUE` expecting cache; confirm "no cache-miss warnings" instead.
- `REFRESH=TRUE` is only needed when your flow invokes a cacheable DIAL deployment as a tool.

### Weak (cacheable) models can't do multi-step tool reasoning
Don't assume the cacheable non-agent model (`gpt-4.1`) can drive your flow. It fixates and loops on the first tool, ignoring follow-up instructions — verified across many prompt rewrites; it's a capability wall, not a wording problem. Use a capable orchestrator (`gpt-5.2`, `gpt-5`, `claude-opus-4-6`, `gemini-2.5-pro`). These are all in `AGENT_MODELS` (live). **Verify every model you list/pin actually passes — don't list on faith.** Let the test use the suite's `--model` (no `model=` pin, no `models_applicable_for_test`) unless you have a reason; record verified models in a comment.

### Every called tool must be expected; every expected tool must be called
`ResponseValidator._check_unexpected_tools` fails the test if the agent calls any tool not in your `tool_calls` list (only `internal_skills_read_skill` is auto-allowed). And argument validation requires each expected `ToolCall` to match ≥1 actual call. So: **write a tight, prescriptive prompt** that names exactly the tools you assert and steers the agent away from alternatives (e.g. "use internal_file_search" — not read_lines — "and do not call any other tool"). Loose prompts → unexpected-tool failures or wrong-tool branches. Also pick the **smallest `config_file_set`** that still exposes the tools you need (e.g. `integration_simple` instead of `integration`) to shrink the menu the agent can stray into — tools enabled via app config like `features.dial_files` stay available regardless of the set.

### Tool-result attachments don't reach the final message
An attachment set on a `ToolCallResult` does NOT appear in the response's `custom_content.attachments`, so `AttachmentCheck` can't see it. Assert feature effects through the **tool-call history** (`check_tool_calls` reads `state[tool_execution_history]` — all calls + args), e.g. a custom-function arg check that a path contains `offloaded-responses`, not via attachments.

### Stale test server serves old routes
`make integration_test` starts/stops its own MCP+REST server, but a server left running from a prior session stays bound to `:8002`/`:8003` and serves the OLD code → your new route 404s. If a new endpoint 404s: `make stop_test_server`; `lsof -ti:8002,8003 | xargs kill -9`; restart. Always verify a new route with `curl` before running the test.

## Adding REST test tooling (4 coordinated edits)

To make a REST tool available to the agent, edit all four:
1. `test_runner/cache/rest_api_tool_test_mixin.py` — add an `async def rest_test_<x>(self, request)` handler.
2. `data_server_for_tests.py` — register the route in `RestTestServer.register_rest_test_routes`.
3. `test_runner/test_rest_toolset.json` — add the tool to `shapes_box_toolset.tools` (name `<x>` → exposed as `shapes_box_toolset_<x>`).
4. `test_runner/utils/tool_names.py` — add the `ToolNames` constant.

MCP test tools live in `test_runner/mcp_server/mcp_http_test_server.py` (`@mcp.tool`). The app config the tests use is `TestConfig.create_app_configuration` (`test_runner/config.py`) — it already enables `features.dial_files`; preview features are on via `.env` (`ENABLE_PREVIEW_FEATURES=true`).

## Verification

```bash
make start_test_server                                    # or rely on make integration_test
curl "http://localhost:8002/<your_route>"                 # confirm new tooling before testing
poetry run pytest src/tests/integration_tests/test_<x>.py --model=gpt-5.2-2025-12-11 \
    -p no:cacheprovider -o addopts="" 2>&1 | tail -40
```
- A pass with **no** "No cached value found" warning means the flow needed no cache (expected for REST/internal/MCP-only flows).
- Because the orchestrator is live, run it **2–3 times** to confirm stability before declaring done.
- To check argument/tool failures, grep the output for `called N times` and the `tool_calls` history.

## Common mistakes

| Symptom | Cause / fix |
|---|---|
| Agent loops on one tool, never advances | Weak model (`gpt-4.1`). Use a capable AGENT_MODELS orchestrator. |
| "Unexpected tool 'X' called" | Prompt let the agent pick a tool you didn't assert. Tighten the prompt; or add X to `tool_calls`. |
| New endpoint returns 404 | Stale test server on `:8002`. Kill & restart; `curl`-verify first. |
| Planning to commit `.response` files for a REST-only test | No cacheable deployment calls exist → nothing to commit. |
| AttachmentCheck never matches an offloaded/tool-produced file | Tool-result attachments don't propagate. Assert via tool-call history instead. |
| Test flakes run-to-run | Orchestrator is live. Make the prompt more prescriptive; verify across runs. |
