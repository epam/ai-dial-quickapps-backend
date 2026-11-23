# Design: Async (Non-Blocking) Hooks

- **Status:** Draft
- **Issue:** [#616](https://github.com/epam/ai-dial-quickapps-backend/issues/616)
- **Dependencies:**
  - [Hook Context, Parameter Templating, and Lifecycle Events](hook_context_and_lifecycle_events.md) — this is its
    "Phase 2: background execution"

> **Review note.** Every open concern below lists its options and a **Proposed decision**. Decisions are
> proposals for the team to confirm or change. Concerns marked **needs confirmation** have no agreed answer yet.

## Problem Statement

Every hook runs inline and is awaited ([Hooks](../hooks.md)):

- `on_request_start` hooks run before the first LLM call, so a slow hook delays the whole answer.
- `on_completion` hooks run after the final answer is streamed but **before the response is closed**, so a slow
  side-effect hook keeps the user's stream open after the answer is already visible.

The motivating case is the agent-memory save: an `on_completion` hook calls the memory MCP tool `save`, which runs
an LLM call and writes files to DIAL storage and takes up to 120 s (`timeout_seconds: 120`). Nobody waits for its
result, yet the user's stream stays open for the whole save.

`timeout_seconds` only caps the delay; it does not remove it. Making the tool itself fire-and-forget pushes the
problem to every tool author and does not help with third-party MCP or REST tools.

## Design Goals

- A hook can be marked to run without delaying the response.
- The save keeps working after the user's stream has closed, including when the hook calls a DIAL application
  (which itself calls tools).
- Failures and timeouts never reach the user.
- Background work is bounded: concurrency, lifetime, and behaviour on shutdown are defined.
- Default behaviour (`async` omitted) is unchanged.

## Use Cases

### UC-1: Memory save after the answer

**Trigger:** An `on_completion` hook with `async: true` calls the memory `save` tool.
**Behavior:** The call is started and accepted by DIAL Core before the response closes; the response then closes
without waiting for the save to finish.
**Outcome:** The user sees the stream end right after the answer. The save completes in the background; a failure
is only logged.

### UC-2: Hook that calls another application

**Trigger:** The async hook's tool is a DIAL application (`deployment-tool`), which in turn calls an MCP tool.
**Behavior:** The nested application keeps running after the outer response closed and uses its own per-request key.
**Outcome:** Same as UC-1, one hop deeper.

## Background: what DIAL Core allows

Per-request keys are issued by Core only, for a request it routes to a deployment, and are invalidated when that
request completes ([Per-request keys](https://github.com/epam/ai-dial/blob/main/docs_v2/3.building-with-dial/7.working-with-dial-resources/5.per-request-keys.md)).
A non-root key is derived from a valid parent key and carries a copy of the parent's data. The sharing endpoint
`per-request-permissions/grant` shares resources with another deployment for the request timeline; it does **not**
extend key lifetime, so it is not a solution here. There is no public endpoint to mint a key.

The risk was that detached work would fail with 401 once the user's request ended. The experiment below tested this.

### Experiment (prototype on branch `feat/616-async-hooks`)

Local Core, a slow MCP server (`slow_save`: sleeps 20 s, then calls Core with the forwarded `Api-Key` and writes a
file to `appdata`), and a prototype that starts the hook as a detached task and keeps the MCP session open.

| Scenario | Result |
|---|---|
| Hook call starts **after** the response closed | Core returns **401** on the MCP session; the call never reaches the tool |
| Hook call reaches Core **before** the response closes | `slow_save` runs; 18–20 s after the close `GET /v1/bucket` and the file `PUT` return **200** |
| Test app → async hook → Agent application → MCP `slow_save` (two hops) | The agent app made its own model call and its own MCP call after the outer response closed; both succeeded |
| Result return of the detached MCP call | Core sometimes answers **401** when the result is returned, although the work finished |

Conclusions:

1. **No Core change is needed.** A call already accepted by Core runs on its own child key, which outlives the
   user's request.
2. The call must be **accepted by Core before the response closes**.
3. A 401 on the result return can happen and must not be treated as a failure of the work.
4. Detached work writes into the already-closed choice (`Trying to create stage to a closed choice`); this is
   addressed in [Secondary Fixes](#secondary-fixes).

## Proposed Design

### 1. Configuration shape

**Options**

| Option | Notes |
|---|---|
| `async: bool` on the hook, `on_completion` only | Smallest surface; matches the motivating case |
| `async: bool` on both events, injecting nothing for `on_request_start` | Allows side-effect-only request-start hooks; adds a second mode with little value |
| Execution mode enum (`inline` / `background`) | Room for future modes; premature today |

**Proposed decision:** `async: bool` (default `false`), accepted only for `on_completion`. The manifest validator
rejects `async: true` on `on_request_start`, because a background hook cannot inject its result into the current
request. Relaxing this later is backward compatible. The field is declared with the JSON alias `async` because
`async` is a Python keyword.

### 2. Knowing that Core accepted the call

The response must not close before every async hook's call has reached Core (conclusion 2). **Needs confirmation.**

| Option | Notes |
|---|---|
| Real signal | The HTTP client sets an event when the first response headers arrive from Core (httpx response event hook for MCP; first chunk for deployment tools). The response closes after all signals, with a capped maximum wait. Exact, but touches the MCP transport and the deployment client |
| Fixed grace delay | A configurable wait (e.g. 2–3 s) after starting async hooks, as in the prototype. Simple, but always adds delay and can be too short on a slow Core |
| Both | Use the signal where the transport provides it, fall back to a short capped wait otherwise |

**Proposed decision:** both — signal first, capped fallback. If the cap expires the hook is left running and a
warning is logged.

### 3. Lifetime of the session and request-scoped objects

The hook's tool uses request-scoped objects (MCP session, forwarded headers). **Needs confirmation.**

| Option | Notes |
|---|---|
| Defer request teardown | `RequestAsyncCloseRegistry` tracks detached tasks; `aclose_all` no longer blocks the request and runs the closers after the tasks finish. Small change; reuses session and the forwarded key |
| Separate session per hook | The hook opens its own session independent of the request. Better isolation, but tools and clients are request-scoped today, so it needs a refactor |

**Proposed decision:** defer teardown. The extra lifetime of request-scoped objects is bounded by the hook's
`timeout_seconds`. A separate-session design can replace this later without changing the manifest.

### 4. Concurrency limit

**Needs confirmation.**

| Option | Notes |
|---|---|
| Global env limit, drop when full | e.g. `ASYNC_HOOKS_MAX_CONCURRENT` (default 50), semaphore; the hook is skipped with a warning when full. Saves are best-effort |
| Global env limit, run inline when full | Nothing is lost, but the response is delayed under load |
| Per-app manifest limit | More flexible; one noisy app can still exhaust the process, so it still needs a global limit |

**Proposed decision:** global env limit, drop with a warning. Dropping is visible in logs and protects the process.

### 5. Shutdown

**Needs confirmation.**

| Option | Notes |
|---|---|
| Drain with a grace period, then cancel | e.g. wait up to 30 s for running hooks, cancel the rest and log how many |
| Cancel immediately | Simplest; every in-flight save is lost on deploy |

**Proposed decision:** drain with a grace period, then cancel and log.

### 6. Ordering against synchronous hooks

| Option | Notes |
|---|---|
| Start async hooks first, then run sync hooks | Async calls reach Core while the key is certainly valid and overlap with sync hooks |
| Run in manifest order | Predictable, but an async hook listed last starts closest to the response close |

**Proposed decision:** start all async hooks first (in manifest order), wait for their accepted signals, then run
the sync hooks in manifest order.

### 7. Failure handling

A background hook never fails the request and its result is discarded. Failures and timeouts are logged. A 401 on
the result return after the work was accepted is logged at info, since the work may have completed (conclusion 3).
Logs carry metadata only (hook name, event, elapsed, outcome), per the logging policy.

### 8. Hooks that call DIAL applications

**Proposed decision:** allowed. The experiment shows the nested application keeps working (UC-2). Documented as
best-effort: no result, no error reaches the user.

### 9. Changes to DIAL Core

**Proposed decision:** none. If a Core release ever cancels detached downstream calls, the fallback is a request
to Core for a bounded grace period on per-request keys for detached work.

## Secondary Fixes

### Stages created on a closed choice

Detached work (and a nested application's stage deltas propagated onto the outer choice) tries to create stages
after the choice is closed. The SDK logs an error and raises. **Decision:** check `Choice.closed` before creating
a stage; if closed, log a warning and skip. Never raise. Applied to the two `create_stage` calls in
`ChoiceUiSink`, to `UsageStatisticsService`, and to the execution-time stage in `_quick_app_completion`. This is
independent of the async feature and safe to ship on its own.

## Out of Scope

- **Async `on_request_start` hooks.** Needs a rule for injecting a late result; deferred.
- **Retries and persistence of background hooks** (a durable queue). Saves are best-effort; a queue is a
  separate system.
- **Separate session per hook.** See concern 3.

## Configuration / Usage Examples

```json
{
  "kind": "tool_call",
  "event": "on_completion",
  "async": true,
  "timeout_seconds": 120,
  "toolset_name": "dial-llm-wiki-memory",
  "tool_name": "save",
  "arguments": {
    "input_map": {
      "user asked": {"$eval": "last_user_message.content"},
      "assistant responded": {"$eval": "last_assistant_message.content"}
    }
  }
}
```

## Migration

### Breaking changes

None. `async` defaults to `false`.

### Non-breaking changes

Manifests that set `async: true` on `on_request_start` are rejected when loaded. The field is new, so no existing
manifest is affected.

## Summary of Changes

- **Config:** `async` on `ToolCallHookConfig` (`on_completion` only).
- **`HookDispatcher`:** start async hooks as tracked background tasks; accepted-signal wait; concurrency limit.
- **`RequestAsyncCloseRegistry`:** track detached tasks; defer teardown until they finish.
- **MCP / deployment clients:** emit the "accepted" signal on first response headers.
- **Settings:** concurrency limit and shutdown grace period (env).
- **Stage creation sites:** `Choice.closed` guard.
- **Docs:** `docs/hooks.md`, `CONFIGURATION.md`, JSON schema (`make dump_app_schema`).
