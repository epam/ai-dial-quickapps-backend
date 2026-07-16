# Design: Log Levels & Content Policy

- **Status:** Approved
- **Approved:** 2026-07-14
- **Issue:** [#434](https://github.com/epam/ai-dial-quickapps-backend/issues/434) (epic [#441](https://github.com/epam/ai-dial-quickapps-backend/issues/441))
- **Dependencies:**
  - None. Informed by the logging review of 2026-07-13. Gates the implementation issues
    [#435](https://github.com/epam/ai-dial-quickapps-backend/issues/435) (lifecycle events + level rebalance) and
    [#436](https://github.com/epam/ai-dial-quickapps-backend/issues/436) (content sweep + payload switch).

## Problem Statement

INFO-level logs currently say almost nothing about what a request did. The request lifecycle — which app was
called, how many orchestrator iterations ran, which tools executed, how long they took, how the request ended —
is visible only at DEBUG, where it comes bundled with full payload dumps: complete message contexts, chat-completion
configs including forwarded headers, tool-call arguments, and raw LLM responses. Investigating a production issue at
INFO is impossible; investigating at DEBUG is a privacy hazard, because DEBUG is routinely enabled in live
environments during incidents and immediately floods aggregated logs with conversation content.

Two policies are missing, and their absence compounds:

1. **No documented level semantics.** Nothing states what DEBUG/INFO/WARNING/ERROR mean for this service, so levels
   drift with each change — routine per-request outcomes log at INFO, while recoverable conditions log at ERROR.
2. **No content policy.** Nothing states what may appear in a log record, so whole objects (messages, arguments,
   headers, response bodies, signed URLs) are logged wherever a developer found them convenient. The gap extends
   beyond quickapp's own call sites: the `openai` client library logs complete chat-completion request bodies at
   DEBUG, and `LoggingConfig` pins it — together with `httpx` and `httpcore` — to the root `LOG_LEVEL`, so a single
   env change floods aggregated logs with payloads no quickapp code ever emitted.

### Audit of current INFO call sites

The full inventory of today's INFO records, grouped by disposition (the design's first input):

| Group | Sites | Assessment |
|---|---|---|
| Startup summaries | `_QuickAppApplication` ("All modules successfully configured"), `PredefinedContentProvider` (layer/merge summaries) | Correct — one-time, structural. |
| Operational events | `FallbackProcessor` ("Fallback applied for tool_call_id=…"), `SessionManager` (py-interpreter session renewal), `CatchAllScanner` (deprecated-config advisories) | Correct — noteworthy, metadata-only. |
| Interactive login | `_InteractiveLoginService` (request, skip, timeout, results — 4 sites) | Right level, wrong shape — legitimate lifecycle events, to be normalized into the event list below. |
| Per-request noise | `_GetContentTool` (5 rejection variants), `_AttachmentGetContentInjector` (2 skip variants), `AgentSkillsProvider` ("Loaded N skill(s)") | Routine, expected outcomes — belong at DEBUG. |
| Request lifecycle | — | **Absent entirely.** Nothing at INFO records arrival, model calls, tool executions, or completion. |

### Related mislevels

- `StagedBaseTool` — the execution choke point for all four tool types — logs ERROR (`logger.exception`, two sites)
  for every tool failure immediately before handing it to the fallback processor. When no strategy matches and the
  exception propagates, the same failure is logged at ERROR a second time by `_QuickAppCompletion`.
- `McpTool` logs ERROR (including the full tool response body) for a failure it then raises for fallback strategies
  to handle — the error may never affect the request outcome.
- `DialCompletionService` logs WARNING for an empty content parameter, a case the code treats as normal.

## Design Goals

- INFO alone is sufficient to reconstruct **what a request did** during an incident: arrival, each model call, each
  tool invocation by name with duration and outcome, fallbacks, completion.
- No user/AI message content, tool-call argument values, response bodies, header values, or URL query strings are
  emitted by quickapp's own call sites at **any** level — including DEBUG — and payload-capable third-party loggers
  are capped so that raising any log level alone never brings payloads into the pipeline. Content always requires
  the explicit opt-in switch.
- Payload-bearing debug logging exists only behind an explicit opt-in switch, with truncation, never as a side
  effect of setting a log level.
- Level semantics are written down once (this document), later codified in `CODESTYLE.md` so reviews can enforce
  them.
- Existing INFO noise is demoted and the known mislevels fixed, so the INFO channel stays readable.

---

## Use Cases

### UC-1: Production incident triaged at INFO

**Trigger:** An operator investigates a slow or failed request in a production environment running at INFO.
**Behavior:** The logs for the request read as a compact skeleton: request received (deployment, message/attachment
counts), each iteration's model call (duration, tool calls requested by name), each tool execution (name, duration,
outcome), any fallback or recovery, and a completion record (iterations, total duration, outcome).
**Outcome:** The operator identifies which step failed or stalled — without raising the log level and without any
conversation content entering the log pipeline.

### UC-2: DEBUG enabled in a live environment

**Trigger:** During an incident, an operator raises verbosity on a shared environment — `QUICKAPP_LOG_LEVEL=DEBUG`,
`LOG_LEVEL=DEBUG`, or both.
**Behavior:** DEBUG adds control-flow detail and structure summaries (counts, sizes, states) but still no message
bodies, tool arguments, or response payloads: quickapp's content-bearing records and the payload-capable third-party
loggers (`openai`, `httpx`, `httpcore`) are both gated by the payload switch, which is off.
**Outcome:** Verbose diagnostics without a privacy or compliance exposure — regardless of which level knob was
raised.

### UC-3: Local payload debugging

**Trigger:** A developer needs to see what the LLM actually received while debugging a prompt-assembly problem
locally.
**Behavior:** The developer sets `LOG_PAYLOADS=true` together with DEBUG. Content-bearing records (message context,
tool arguments, raw responses) are emitted, each payload field truncated to a configurable cap.
**Outcome:** Full-fidelity local debugging, explicitly opted into, structurally impossible to trip over by only
raising the log level.

### UC-4: Tool failure absorbed by a fallback

**Trigger:** An MCP tool returns an error, and a catch-all fallback strategy handles it.
**Behavior:** `McpTool` detects the error and raises, logging nothing above DEBUG. The `StagedBaseTool` choke
point — which applies the fallback — logs the single WARNING (tool name, exception type — no response body); the
fallback processor logs its application at INFO; and the tool-completion event fires at INFO with `outcome=error`.
No ERROR record is emitted, because the failure never reached the layer that owns final failure handling.
**Outcome:** The narrative shows a handled failure as exactly one WARNING plus two INFO events; ERROR remains
reserved for failures that actually affect the request outcome.

### UC-5: Unhandled failure — the single ERROR

**Trigger:** A tool failure has no matching fallback strategy (or a non-tool step raises), and the exception
propagates out of the orchestrator.
**Behavior:** Intermediate layers add at most WARNING records as the exception travels. `_QuickAppCompletion` — the
final owner — logs the single ERROR with the stack trace and an 8-char `error_reference`, and the completion event
fires with `outcome=failed` carrying the same reference.
**Outcome:** Exactly one ERROR per failed request, correlated with both the user-visible error message and the
request skeleton — no second ERROR from the tool layer, as happens today.

---

## Proposed Design

The design has four parts: level semantics, the INFO event list, the content rule, and the payload-debugging
switch. The first two are implemented by #435, the last two by #436.

### 1. Level semantics

| Level | Meaning for this service | Examples |
|---|---|---|
| **DEBUG** | Developer diagnostics: control flow, intermediate values, structure summaries. Verbose, not expected to read as a narrative. Subject to the content rule like every other level — payload content only via the payload switch. | State-holder summaries, routine rejections/skips, perf reports |
| **INFO** | The operational narrative: startup/configuration summaries plus the per-request lifecycle skeleton defined below. Metadata-only; low, bounded volume per request. | Request received, model call, tool executed, fallback applied, request completed |
| **WARNING** | Something unexpected happened and the service handled it; the request continues, possibly degraded. No per-occurrence action needed, but patterns deserve attention. | Stream recovery applied, unsupported content block tolerated, tool failure handed to a fallback, deprecated config encountered |
| **ERROR** | A failure that affected the request outcome or cost the service functionality; each occurrence is worth investigating. | Unhandled request exception (with `error_reference`), toolset initialization failure surfaced to the user |

**Ownership rule for ERROR:** a failure is logged at ERROR exactly once, by the layer that owns its final handling.
A layer that hands the failure onward — to a fallback strategy, a recovery policy, or by (re-)raising for an
upstream handler — logs at WARNING or not at all. In the request path the final owner is `_QuickAppCompletion`
(the existing `error_reference` record); `StagedBaseTool`, which catches tool failures only to route them into
fallback processing, is a hands-onward layer and moves to WARNING (see Secondary Fixes). The single-writer
discipline extends to WARNING: one failure gets one salient record per severity. For tool failures that record is
written by the `StagedBaseTool` choke point — layers beneath it that merely detect and raise (e.g. `McpTool`) log
at most structure-level DEBUG detail. This both fixes the current mislevels and eliminates the duplicate emission
of a single failure at several layers.

These semantics are codified in `CODESTYLE.md` §9 (Logging and error handling) as part of #435; until then this
document is canonical.

### 2. The INFO event list — the request skeleton

One request at INFO produces the following events, each metadata-only. Owners are the components that already have
the data (durations reuse the existing `PerformanceTimer` periods where practical):

| # | Event | Owner | Fields |
|---|---|---|---|
| 1 | Request received | `_QuickAppCompletion` (after context setup) | orchestrator deployment id, message count, attachment count |
| 2 | Request initialized | `_QuickAppCompletion` (after initializers) | tool count per toolset type, skill count, context count |
| 3 | Interactive login requested / resolved | `_InteractiveLoginService` | toolset ids, per-toolset outcome (`success`/`denied`/`timeout`/`error`/`no_channel`), duration |
| 4 | Model call completed | `Orchestrator` (per iteration) | iteration number, deployment id, duration, finish kind (final answer / tool calls), requested tool names, content length, token usage when available |
| 5 | Tool call completed | `StagedBaseTool` (choke point for all four tool types) | tool name, tool_call_id, duration, outcome (`success`/`error`) |
| 6 | Fallback applied | `FallbackProcessor` (exists today) | tool_call_id, strategy |
| 7 | Request completed | `_QuickAppCompletion` | outcome (`completed` / `external_tool_calls` / `failed`), iteration count, total tool calls, total duration, `error_reference` on failure |

Notes:

- **No separate "tool call started" event.** The model-call event (4) lists the requested tool names; a hung tool is
  identified as the requested name with no matching completion event (5). This keeps the skeleton at roughly
  5–10 lines for a typical request.
- **Interactive login (3) stays at INFO** even though the earlier review classed its records as noise: the
  round-trip blocks on end-user interaction, is bounded by a timeout, and its outcome changes tool availability —
  exactly the kind of step an incident investigation needs. The existing four ad-hoc records are reshaped into the
  request/resolved pair rather than removed.
- **A handled tool failure produces exactly three records:** one WARNING from `StagedBaseTool` (tool name,
  tool_call_id, exception type — the failure itself, with stack trace), the INFO fallback event (6), and the INFO
  completion event (5) with `outcome=error`. Detection layers beneath the choke point add nothing above DEBUG.
- **On failure, ERROR complements the skeleton.** The existing `logger.exception` record with `error_reference`
  remains the single ERROR record; the completion event (7) still fires with `outcome=failed` and the same
  `error_reference` so the narrative is closed and correlated.
- **Event shape.** Events use a stable message prefix plus `key=value` fields rather than free prose, so that #438
  (JSON output) and #439 (request-scoped ids) can later lift the same fields into structured attributes without
  rewording the events.

### 3. The content rule

Applies to **all** levels, DEBUG included.

**Allowed (structure):** roles; counts and sizes/lengths; durations; tool, skill, deployment, and model names;
identifiers (tool_call_id, toolset id, session id, `error_reference`); statuses and outcome enums; error codes and
types; finish reasons; MIME types; HTTP status codes; header **names**; URLs stripped to scheme, host, and path.

**Forbidden (content):** user/system/assistant/tool message bodies; tool-call argument values; tool and LLM response
bodies; attachment content; header **values** (forwarded `X-*` headers may carry auth-adjacent material); URL query
strings and fragments (signed URLs and tokens live there).

Boundary cases:

- **URLs.** Log scheme + host + path only. DIAL relative file paths (`files/...`) are identifying metadata and may
  be logged as-is once the query string is stripped.
- **Exceptions.** Stack traces and exception messages are permitted — they are the diagnostic. The corollary is
  that exceptions raised by our own code must not embed payload content in their messages (today
  `MCPToolErrorException` carries the tool response body; #436 reduces it to structure). Third-party exception
  text is accepted as-is.
- **Enum-valued maps** (e.g. the login result map — toolset id → outcome) are structure, not content.

The rule is an **allowlist**: when in doubt, a value is content. Redacting known-sensitive keys out of full dumps
was considered and rejected — denylisting content is fragile; allowlisting structure is robust by construction.

### 4. The payload-debugging switch

Payload-bearing records are retained for local development only, behind an explicit opt-in:

| Variable | Default | Semantics |
|---|---|---|
| `LOG_PAYLOADS` | `false` | When `false`, content-bearing records are not emitted at all — at any level. When `true`, they are emitted at DEBUG. |
| `LOG_PAYLOADS_MAX_LENGTH` | `2000` | Per-field character cap applied to every payload value when the switch is on; longer values are truncated with an ellipsis marker. Inert when `LOG_PAYLOADS=false`. |

Both variables live in `LoggingSettings` (`config/logging_settings.py`), alongside the existing level knobs. The
generic `LOG_` prefix (rather than `QUICKAPP_`) is deliberate: like `LOG_LEVEL` and `LOG_FORMAT`, the switch
governs the whole log pipeline — including the third-party cap below — not just the `quickapp` logger hierarchy.

- The switch is **additive to the level**: content appears only when both `QUICKAPP_LOG_LEVEL=DEBUG` (verbosity)
  and `LOG_PAYLOADS=true` (content) are set. Raising the level alone never reveals payloads.
- **Payload-capable third-party loggers are gated by the same switch.** The `openai` client logs complete
  chat-completion request bodies at DEBUG, and `httpx`/`httpcore` log wire-level detail; today all three follow the
  root `LOG_LEVEL`. `LoggingConfig` caps these three loggers at INFO while `LOG_PAYLOADS=false`, regardless of
  `LOG_LEVEL`; setting the switch lifts the cap, and `LOG_LEVEL` applies to them as before. Their records are
  emitted as-is — the truncation cap governs only quickapp's own records. The trade-off is explicit: wire-level
  third-party debugging now requires the same opt-in as payload debugging, because it *is* payload debugging.
- Covered quickapp records: the chat-completion config dump, orchestrator message-context dumps, tool-call
  arguments, tool and raw LLM responses. In #436 each of these sites emits an unconditional structure summary at
  DEBUG (roles, counts, sizes) and the payload detail only under the switch.
- Even with the switch on, forwarded **header values are never logged by quickapp code** — there is no legitimate
  debugging need that outweighs replaying auth material into logs.
- Documentation (`README.md` / `CONFIGURATION.md`) must carry an explicit warning that the switch is intended for
  local development and must not be enabled in shared environments.

### 5. Level rebalance — disposition of existing INFO records

| Site | Current | New | Rationale |
|---|---|---|---|
| `_GetContentTool` rejection variants (5) | INFO | DEBUG | Routine outcomes, already returned to the model as tool results |
| `_AttachmentGetContentInjector` skips (2) | INFO | DEBUG | Routine per-attachment bookkeeping |
| `AgentSkillsProvider` "Loaded N skill(s)" | INFO | DEBUG | Superseded by the request-initialized event (2), which carries the skill count |
| `_InteractiveLoginService` records (4) | INFO | INFO | Kept; reshaped into event 3 (see note above) |
| Startup summaries, fallback applied, session renewal, catch-all advisories | INFO | INFO | Correct as-is |

WARNING/ERROR-level corrections are consolidated under **Secondary Fixes** below.

---

## Secondary Fixes

Level corrections that follow from the ownership rule and the content rule but sit outside the INFO skeleton. All
delivered by #435; content stripping by #436.

- **`StagedBaseTool` tool-failure records: ERROR → WARNING.** The choke point's two `logger.exception` sites fire
  immediately before the failure is handed to `FallbackProcessor` — a hands-onward layer under the ownership rule.
  As WARNING they become the single failure record for every tool type (see the three-record set in §2):
  fallback-absorbed failures produce WARNING + fallback INFO + completion INFO; propagating failures leave the
  single ERROR to `_QuickAppCompletion`.
- **`McpTool` `isError` handling: ERROR → DEBUG, structure only.** `McpTool` merely detects the error and raises
  `MCPToolErrorException`; the `StagedBaseTool` choke point already owns the WARNING for the same failure, and a
  second WARNING would recreate the duplicate emission one level down. The record additionally embeds the tool
  response body and structured content, which violates the content rule; #436 reduces it to structure (tool name,
  content length, structured-content presence).
- **`DialCompletionService` empty-content record: WARNING → DEBUG.** The code treats the case as normal; at most a
  configuration smell.

---

## Out of Scope

- **Request-scoped ids on every record** — #439. The event shape (stable prefix + `key=value` fields) is chosen so
  ids can enrich records later without rewording them.
- **Structured JSON output mode** — #438. Same forward-compatibility argument.
- **Exception-logging conventions** (one blessed pattern, no silent swallows) — #437.
- **User-visible stage disclosure** (what stage wrappers show end users) — #440. The content rule here governs
  server logs only; the stage channel needs its own deliberate policy aligned with the error-handling design.
- **Metrics, tracing, and log-based alerting** — out of scope for the epic.

---

## Configuration / Usage Examples

### One request at INFO level (skeleton)

```
INFO    Request received: deployment=gpt-4o, messages=5, attachments=1
INFO    Request initialized: tools=3 (rest=1, mcp=2), skills=2, contexts=1
INFO    Model call completed: iteration=1, deployment=gpt-4o, duration=2.1s, finish=tool_calls, tools=[search_catalog, get_content]
INFO    Tool call completed: tool=search_catalog, tool_call_id=call_abc, duration=0.4s, outcome=success
WARNING Tool call failed: tool=get_content, tool_call_id=call_def, error=MCPToolErrorException
INFO    Fallback applied: tool_call_id=call_def, strategy=catch_all
INFO    Tool call completed: tool=get_content, tool_call_id=call_def, duration=1.2s, outcome=error
INFO    Model call completed: iteration=2, deployment=gpt-4o, duration=3.0s, finish=stop, content_length=1834, tokens=1210/312
INFO    Request completed: outcome=completed, iterations=2, tool_calls=2, duration=7.2s
```

The handled failure of `get_content` shows the canonical three-record set from §2: one WARNING (the failure), the
fallback INFO event, and the completion INFO event with `outcome=error`.

(Field names are illustrative; #435 fixes the exact wording. The shape — stable prefix, `key=value` pairs — is the
contract.)

### Environment matrix

| `QUICKAPP_LOG_LEVEL` | `LOG_LEVEL` | `LOG_PAYLOADS` | What the logs contain |
|---|---|---|---|
| `INFO` (default) | `INFO` (default) | `false` (default) | The request skeleton + warnings/errors. Production default. |
| `DEBUG` | `INFO` | `false` | + app control flow and structure summaries. Safe for live incident debugging. |
| `DEBUG` | `DEBUG` | `false` | + third-party diagnostics; `openai`/`httpx`/`httpcore` stay capped at INFO. Safe for live incident debugging. |
| `DEBUG` | `DEBUG` | `true` | Everything, including payload content (truncated for quickapp records, as-is for third-party). Local development only. |
| `INFO` | `INFO` | `true` | Same as the first row — payload records are DEBUG-level, so the switch alone reveals nothing. |

---

## Migration

### Breaking changes

None at the API level. Operationally:

- Log **messages are not a stable interface**, but any existing scraping/alerting keyed on current INFO/ERROR
  wording (e.g. the `get_content` rejections at INFO, the tool-layer ERROR records) will need adjustment after
  #435/#436.
- INFO volume grows by the skeleton (roughly 5–10 records per request) and shrinks by the demoted noise; DEBUG
  volume drops sharply because payload dumps move behind the switch.
- Operators who relied on `LOG_LEVEL=DEBUG` to see `openai`/`httpx`/`httpcore` wire logs must now also set
  `LOG_PAYLOADS=true` — the cap is the point of the change.

### Non-breaking changes

- `LOG_PAYLOADS` / `LOG_PAYLOADS_MAX_LENGTH` are new, additive, and off by default — existing deployments see no
  payload content at DEBUG, which is the intended tightening.

## Summary of Changes

| Concern | Change | Delivered by |
|---|---|---|
| Level semantics | Table in this doc; ownership rule for ERROR; codified in `CODESTYLE.md` §9 | #435 |
| INFO request skeleton | 7 events across `_QuickAppCompletion`, `Orchestrator`, `StagedBaseTool`, `_InteractiveLoginService`, `FallbackProcessor` | #435 |
| Level rebalance | INFO demotions (`_GetContentTool`, `_AttachmentGetContentInjector`, `AgentSkillsProvider`) | #435 |
| Secondary fixes | `StagedBaseTool` ERROR→WARNING (single failure record per tool call); `McpTool` `isError` ERROR→DEBUG (structure only); `DialCompletionService` WARNING→DEBUG | #435 (content stripping in #436) |
| Content rule | Allowlist policy; payload dumps replaced by structure summaries; URL query-string stripping; header values banned | #436 |
| Payload switch | `LOG_PAYLOADS` + `LOG_PAYLOADS_MAX_LENGTH` in `LoggingSettings`, DEBUG-level, truncated, documented with warnings | #436 |
| Third-party payload cap | `openai`/`httpx`/`httpcore` capped at INFO by `LoggingConfig` unless `LOG_PAYLOADS=true` | #436 |
