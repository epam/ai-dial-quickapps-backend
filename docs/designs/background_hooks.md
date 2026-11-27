# Design: Background (Non-Blocking) Hooks

- **Status:** Implemented
- **Issue:** [#616](https://github.com/epam/ai-dial-quickapps-backend/issues/616)
- **User-facing:** [CONFIGURATION - Hooks](../../CONFIGURATION.md#hooks-configuration) / [Hooks guide: background hooks](../hooks.md#background-hooks)
- **Dependencies:**
  - [Hook Context, Parameter Templating, and Lifecycle Events](hook_context_and_lifecycle_events.md) — this is its
    "Phase 2: background execution"

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
- Default behaviour (`execution` omitted) is unchanged.

## Use Cases

### UC-1: Memory save after the answer

**Trigger:** An `on_completion` hook with `execution: background` calls the memory `save` tool.
**Behavior:** The call is started and accepted by DIAL Core before the response closes; the response then closes
without waiting for the save to finish.
**Outcome:** The save completes in the background; a failure is only logged. A save that finishes within the hold
period adds no more than its run time; a slower one holds the stream open for the whole hold period (3 s by
default) after the answer, which is the normal case for a long save.

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

### Experiment (prototype)

Local Core, a slow MCP server (`slow_save`: sleeps 20 s, then calls Core with the forwarded `Api-Key` and writes a
file to `appdata`), and a prototype that starts the hook as a detached task and keeps the MCP session open.

| Scenario | Result |
|---|---|
| Hook call starts **after** the response closed | Core returns **401** on the MCP session; the call never reaches the tool |
| Hook call reaches Core **before** the response closes | `slow_save` runs; 18–20 s after the close `GET /v1/bucket` and the file `PUT` return **200** |
| Test app → async hook → Agent application → MCP `slow_save` (two hops) | The agent app made its own model call and its own MCP call after the outer response closed; both succeeded |
| Result return of the detached MCP call | Core sometimes answers **401** when the result is returned, although the work finished |
| Response headers of a slow MCP `tools/call` through Core (8 s tool) | Arrive at 9.2 s together with the body; straight to the MCP server they arrive at 0 s. Core buffers them, so they cannot serve as an "accepted" signal |

Conclusions:

1. **No Core change is needed.** A call already accepted by Core runs on its own child key, which outlives the
   user's request.
2. The call must be **accepted by Core before the response closes**.
3. A 401 on the result return can happen and must not be treated as a failure of the work.
4. Detached work that creates stages writes into the already-closed choice (`Trying to create stage to a
   closed choice`); a background hook therefore runs [without any stage](#6-no-ui-no-interaction-a-stage-less-call).

## Proposed Design

### 1. Configuration shape

`execution: blocking | background`, a `StrEnum` (`HookExecution`) on the hook, default `blocking`, valid only for
`on_completion`. This is the shape the parent design prescribes ([Schema evolution
rule 1](hook_context_and_lifecycle_events.md#schema-evolution-rules): a closed set of values is an enum, never a
`bool`); a later mode (for example a durable queue) becomes a new member instead of a breaking change.

The manifest validator rejects `execution: background` on `on_request_start`, because a background hook cannot
inject its result into the current request. `execution: blocking` is accepted on every event: it is the default,
and a dumped config always carries it, so rejecting it would break dump → validate round trips. (The parent
design says explicitly setting the field on `on_request_start` is an error; that is relaxed for `blocking`
only.) The validator lives on the base hook config, so a future hook `kind` inherits it.

### 2. Keeping the response open until Core has the call

The response must not close before every background hook's call has reached Core (conclusion 2). Core exposes no
"accepted" signal, so this has to be inferred.

| Option | Notes |
|---|---|
| Response headers as the signal | Rejected for MCP: **measured** — through Core the headers of a slow `tools/call` arrive only when the tool finishes (9.2 s for an 8 s tool), although the MCP server itself sends them immediately. Core buffers them, so the signal arrives too late to be useful. Deployment tools (first streamed chunk) may behave differently; not verified |
| Capped wait | After starting the background hooks, wait until they all finish **or** a hold period expires (3 s by default), whichever comes first. A fast hook adds no delay; a slow one adds at most the hold period; the hooks are not cancelled |
| Fixed delay | Always wait the full period. Rejected: adds delay even for fast hooks |
| Change in Core | Flush headers immediately on proxied calls, or expose an accepted indicator. Rejected for now: needs a Core change this feature does not otherwise need |

**Decision:** capped wait. All background hooks are started first and awaited together, so with several hooks
the delay is at most one hold period, not one per hook. The period is the `BACKGROUND_HOOKS_RESPONSE_HOLD_SECONDS` setting
(default 3 s), and it is measured from the moment the hooks start, so blocking hooks that run meanwhile eat into it
rather than adding to it. It is still a timing assumption: on a Core slower than the hold period the call can
reach Core after the response closed and fail with 401 (logged, never shown to the user). A signal for deployment
tools can be added later as an early exit without changing the manifest.

### 3. Where it lives: the seam schedules, the dispatcher stays mode-agnostic

Follows the parent design's Phasing rule 4. `HookDispatcher` knows nothing about execution modes: `run_hook`
(timeout and failure isolation) applies to any mode, and `run_all` runs a list of hooks in order.
`_CompletionHookRunner`, the `on_completion` seam, splits the event's hooks:

1. For each `background` hook, `dispatcher.run_hook(hook, context)` is created as a coroutine (nothing runs yet).
2. The coroutines go to the `BackgroundHookRegistry` (§4), which starts them as tasks.
3. The `blocking` hooks run in manifest order through `run_all`.
4. The runner waits for the background hooks for what is left of the hold period (§2).

Background hooks therefore start before blocking ones and overlap with them, so their calls reach Core while the
per-request key is certainly valid.

**Lookup timing.** `HookDispatcher.prepare_hook` resolves the hook's handler and tools synchronously, inside the
request, and returns the coroutine that runs it. The registry's task therefore never touches request-scoped objects
on its first step, and the design does not depend on event-loop ordering (`asyncio.wait(..., timeout=0)`).

**Request-scoped objects.** `fastapi_injector` drops the request-scope cache when the response ends, so any
request-scoped lookup made after that raises `KeyError`. The handler and its tools are looked up before the task is created (see "Lookup timing"), inside the request; from then on the tool holds what it needs. Tools must not resolve
request-scoped dependencies lazily inside `arun`; a tool that did would work inside the hold window and fail
afterwards.

### 4. Ownership of the work and of the request's teardown

`BackgroundHookRegistry` is application-scoped (singleton). Per request it receives the hook coroutines and the
request's `RequestAsyncCloseRegistry`:

- **Bounded concurrency.** At most `BACKGROUND_HOOKS_MAX_CONCURRENT` (default 50) hooks run per process. A hook
  that does not fit is rejected: an ERROR is logged and the runner shows a failed stage for it while the response
  is still open (dropping protects the process, and the user can see the loss). Above
  `BACKGROUND_HOOKS_WARN_THRESHOLD` (default 40, below the limit) each newly started hook is logged with a warning,
  an early signal to raise the limit. If nothing is accepted, the teardown stays with the request.
- **Hand-off of teardown.** `RequestAsyncCloseRegistry` counts shares of the teardown. The request holds one;
  `hand_off()` takes one more and returns a callable that releases it (once). The closers run when the *last* share
  is released, whether that is the request's `aclose_all()` or the background registry's release after the request's
  hooks finished (or failed, or were cancelled), so per-request MCP sessions stay open exactly as long as a hook
  uses them. Their extra lifetime is bounded by the hook's `timeout_seconds`.
- **Strong references.** The registry keeps the tasks, so they are not garbage-collected.
- **Timeout.** The per-hook timeout comes from `run_hook`, the same for every mode.

Alternative considered: a separate MCP session per hook, independent of the request. Better isolation, but tools
and clients are request-scoped today, so it needs a refactor. It can replace this later without changing the
manifest.

### 5. Shutdown

A `shutdown` initializer (the counterpart of the existing `startup` ones, run from the application lifespan)
calls `BackgroundHookRegistry.shutdown()`: wait up to `BACKGROUND_HOOKS_SHUTDOWN_GRACE_SECONDS` (default 30) for
running hooks, then cancel the rest and log how many. The teardown of each request still runs after a
cancellation, so MCP sessions are closed. A hard kill (SIGKILL, crash) still loses pending hooks: saves are
best-effort, and a durable queue is out of scope.

### 6. No UI, no interaction: a stage-less call

The parent design's single change point is `ToolCallHookHandler`. For a `background` hook it calls
`tool.arun_in_background(...)` instead of the hidden DEBUG-stage call. This is a separate method rather than a
flag on `arun`, so a tool argument can never collide with a control parameter. `arun_in_background`:

- builds **no stage**, not even an error stage, so nothing touches the response choice (which may be closed). The
  one exception is outside the call: a hook rejected over the concurrency limit gets a failed stage, created by the
  runner while the response is still open (§4). A
  DIAL deployment tool called without a stage has no parent stage, so its nested-application stage deltas have no
  destination on the outer choice either;
- sets a context flag (`is_background_execution()`) for the duration of the call. `InteractiveLoginService`
  returns `NO_CHANNEL` while it is set, so a 401 or an external-service sign-in challenge never opens an
  interactive prompt on a request that has ended, and never retries the tool call (which would run a save twice).

Hook usage is not reported: nothing in the hook path adds to the usage statistics, which are written inside the
request.

### 7. Failure handling

A background hook never fails the request and its result is discarded. Failures and timeouts are logged by the
same two places as for a blocking hook: the tool layer's single `Tool call failed` warning (type and duration, no
body or arguments) and `run_hook`'s timeout/exception lines. A 401 on the result return after the work was
accepted (conclusion 3) is therefore logged at warning level with the rest of the failures; the work may have
completed, so the line is not proof of loss. Logs carry metadata only (hook name, event, elapsed, outcome), per
the logging policy.

### 8. Hooks that call DIAL applications

Allowed. The experiment shows the nested application keeps working (UC-2). Documented as best-effort: no result,
no error reaches the user.

### 9. Changes to DIAL Core

None. If a Core release ever cancels detached downstream calls, the fallback is a request to Core for a bounded
bounded lifetime on per-request keys for detached work.

## Not needed: guards on a closed choice

The prototype wrote into the closed choice (`Trying to create stage to a closed choice`) and patched the four
`create_stage` sites with a `Choice.closed` check. With the stage-less call (§6) no hook code touches the choice
after the request, and the orchestrator's own writes (usage statistics, execution-time stage) run inside the
choice's `with` block, so the guards cannot fire and are not part of this change.

## Known Risks

- **Loss over the concurrency limit.** A background hook that does not fit under
  `BACKGROUND_HOOKS_MAX_CONCURRENT` is not run, and whatever it should have written (for example a memory) is lost.
  It is now visible: an ERROR in the logs and a failed stage for the user, and the warning threshold gives an early
  signal. Size the limit for peak load and alert on the warning. Possible follow-ups: queue instead of reject, or
  fall back to running the hook as `blocking`.
- **Dependence on Core's key behaviour.** The design relies on an observed, undocumented behaviour: Core issues the
  child key for a hook's call only while the user's request is still open (see the experiment above). Holding the
  response open for a few seconds is how we make sure the call arrives in time. Core may change this, and on a slow
  Core the call can still arrive late and get 401. A stable fix needs a supported mechanism in Core (an "accepted"
  signal or key lifetime extension).

## Out of Scope

- **Background `on_request_start` hooks.** Needs a rule for injecting a late result; deferred.
- **Retries and persistence of background hooks** (a durable queue). Saves are best-effort; a queue is a
  separate system.
- **Separate session per hook.** See §4.
- **Per-app concurrency limit.** One global limit protects the process; per-app limits can be added.

## Configuration / Usage Examples

```json
{
  "kind": "tool_call",
  "event": "on_completion",
  "execution": "background",
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

None. `execution` defaults to `blocking`.

### Non-breaking changes

Manifests that set `execution: background` on `on_request_start` are rejected when loaded. The field is new, so
no existing manifest is affected.

## Summary of Changes

- **Config:** `HookExecution` enum and `execution` on the hook config; validator on the base config
  (`background` only for `on_completion`).
- **`_CompletionHookRunner`:** split blocking / background, start background hooks via the registry, hold-period wait.
- **`HookDispatcher`:** mode-agnostic; gains `hooks_for`, `run_all`.
- **`ToolCallHookHandler` / `StagedBaseTool.arun`:** stage-less `arun_in_background` call.
- **`InteractiveLoginService`:** no prompt while the background flag is set.
- **`BackgroundHookRegistry` (new, singleton):** bounded concurrency, hand-off of teardown, drain on shutdown.
- **`RequestAsyncCloseRegistry`:** share-counted teardown, `hand_off()`.
- **Settings (env):** `BACKGROUND_HOOKS_MAX_CONCURRENT`, `BACKGROUND_HOOKS_RESPONSE_HOLD_SECONDS`,
  `BACKGROUND_HOOKS_SHUTDOWN_GRACE_SECONDS`.
- **Lifespan:** `shutdown` initializer type.
- **Docs:** `docs/hooks.md`, `CONFIGURATION.md`, JSON schema (`make dump_app_schema`).
