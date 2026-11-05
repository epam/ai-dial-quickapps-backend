# Design: Context Window Usage on the Last Assistant Message

- **Status:** Implemented
- **User-facing:** [`docs/agent.md`](../agent.md#context-usage)
- **Dependencies:**
  - None

## Problem Statement

The DIAL chat UI wants to show a "Context Window" popover for a conversation (used tokens, percentage of the model's
window, a reserved-for-response band, and later a breakdown by system instructions, tool definitions, messages and
tool results). It needs a machine-readable measure of how much of the context the orchestrator consumed.

Today QuickApps reads per-call token usage from the orchestrator LLM stream (`Orchestrator._run_iteration`) but only
logs it. When `SHOW_USAGE_STATISTICS=true` it also collects `DeploymentUsage` entries and renders them as a markdown
"Usage Statistics" stage. Consequences:

- No structured usage reaches the client; the stage is human-readable text, aggregated across all calls and tools,
  and cannot be used to derive context size.
- Aggregated usage is the wrong measure: context size is determined by the *last* orchestrator call, not by the sum.
- Orchestrator usage is only requested from the model (`stream_options.include_usage`) when `SHOW_USAGE_STATISTICS`
  is on, so the value is unavailable by default.
- The model's context window size is not read anywhere in the backend.

This is phase 1 of a three-phase feature; later phases (breakdown, compaction) are out of scope here.

## Design Goals

- The last assistant message of every user turn carries the context usage of the orchestrator's final LLM call.
- The value is available regardless of `SHOW_USAGE_STATISTICS`.
- The value is persisted with the message so a reloaded conversation still shows it.
- The backend does not need to know the model's context window size; the UI derives percentages.
- No change to the manifest schema and no new env variable.

---

## Use Cases

### UC-1: Multi-step tool turn

**Trigger:** User message makes the orchestrator call the LLM three times with tool calls in between.
**Behavior:** Only the third (final) call's token counts are reported.
**Outcome:** The final assistant message state contains `context_usage` equal to the third call's
`prompt_tokens` and `completion_tokens`.

### UC-2: Provider returns no usage

**Trigger:** The orchestrator model/adapter does not return `usage` in the stream.
**Behavior:** Nothing is recorded.
**Outcome:** `context_usage` is absent; the UI hides the component.

### UC-3: Usage statistics disabled

**Trigger:** `SHOW_USAGE_STATISTICS=false` (default).
**Behavior:** Usage is still requested from the orchestrator model and reported.
**Outcome:** `context_usage` present; no "Usage Statistics" stage is added.

---

## Proposed Design

### Capturing last-call usage

- **What:** `Orchestrator` remembers the `Usage` of the most recent orchestrator LLM call.
- **Owner:** `core/agent/orchestrator.py`.
- **Semantics:** After each call in `_run_iteration`, `stream_result.usage` (when present) overwrites the stored
  value, so the last call wins. Tool and sub-agent usage is excluded: it is not part of the orchestrator's window.
- **Change:** New private attribute, set in the new `_record_usage(...)`, which `_run_iteration` calls after each
  orchestrator call.

### Always requesting orchestrator usage

- **What:** `stream_options.include_usage` is set for orchestrator calls unconditionally.
- **Owner:** `core/agent/_chat_completion_config_builder.py`.
- **Semantics:** Previously gated by `show_usage_statistics`. Deployment-tool calls
  (`dial_completion_service.py`) keep their existing gating.
- **Change:** Remove the gate for the orchestrator path.

### Exposing the value

- **What:** A `context_usage` entry in the choice `custom_content.state`.
- **Owner:** `Orchestrator._persisting_state` via `StateHolder.add_state`.
- **Semantics:** Added before `choice.set_state(...)`, which may be called only once per choice; keys added later
  are lost. Shape:

```json
{"context_usage": {"prompt_tokens": 146000, "completion_tokens": 400}}
```

  Context size = `prompt_tokens + completion_tokens`. The key is omitted when no usage was observed.
- **Change:** New state-key constant and a frozen Pydantic model for the payload. The state restore path
  (`_messages_setup.py`) only unpacks `tool_execution_history`, so the key stays on history messages; the config
  builder strips it (`_strip_client_state`) before messages are sent to the model.

### Trade-off: why state, not a stage or streamed field

State is persisted with the message and needs no SDK change, so history reloads keep the value. A stage is
display-only text; a streamed `custom_fields` chunk is not persisted. The cost: state travels back to the backend
on every request (a few bytes).

---

## Out of Scope

- **Context window size:** not sent. The UI reads it from the model metadata when available. If Core's `limits`
  must be forwarded later, add it to `OrchestratorCapabilities` (metadata is already fetched and cached).
- **Breakdown (system instructions, tool definitions, messages, tool results):** needs per-section tokenization;
  a separate design (phase 2).
- **Reserved-for-response band and "Compact Conversation":** phase 3.
- **Session cost:** already derivable from the Usage Statistics stage; not changed here.

---

## Configuration / Usage Examples

Final assistant message:

```json
{
  "role": "assistant",
  "content": "...",
  "custom_content": {
    "state": {"context_usage": {"prompt_tokens": 146000, "completion_tokens": 400}}
  }
}
```

---

## Migration

### Breaking changes

None.

### Non-breaking changes

A new optional state key. Old messages lack it; clients must treat it as optional. Orchestrator requests now always
ask for usage; providers that reject `stream_options` are not expected (already used when statistics are on).

## Summary of Changes

| Component | Change |
|---|---|
| `_chat_completion_config_builder.py` | Always set `include_usage` for orchestrator calls; strip `context_usage` from history messages |
| `orchestrator.py` | Store last-call usage; add `context_usage` to state before `set_state` |
| state keys / models | New constant + frozen Pydantic payload model |
| tests | Unit: last call wins, absent without usage, independent of `SHOW_USAGE_STATISTICS` |
| `docs/agent.md` | Short note on the field |
