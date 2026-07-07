# Design: Subagent Conversation Mode and Awareness

- **Status:** Implemented

## Problem Statement

When the orchestrator LLM calls a deployment tool (subagent), it has no way to know whether the subagent is stateless (each call is independent) or maintains conversation history. The operator may configure `propagate_history=True` or `conversation_mode=stateful`, which causes the backend to reconstruct and prepend prior `[user, assistant]` exchanges on each call — but the LLM is unaware of this. This creates two distinct problems.

### 1. Redundant context injection

The LLM's universal fallback assumption is that every tool call is stateless. So when it calls a history-aware subagent for the second time — say, to provide an employee ID that the subagent asked for — it re-summarizes the entire prior exchange into `query`:

> "Previously you asked me to assign badge 'Happy 5th Anniversary' to John Smith and requested an EmployeeID. The ID is 123456, please proceed."

But because `conversation_mode=stateful`, the backend has already reconstructed and prepended the prior `[user, assistant]` exchange. The subagent now receives the prior context twice: once in the prepended history, once in the new `query`. This causes confusion, wasted tokens, and potentially incorrect behavior.

The LLM should instead send only the **delta** — the new information that wasn't in the prior exchange:

> "123456"

### 2. No conversation thread isolation across multiple subagent instances

`_extract_tool_history` currently identifies prior exchanges by **tool name only**. When the LLM calls the same tool multiple times in parallel — for example, spinning up two independent research subagents — all prior calls to that tool name pool into a single history. The LLM receives back clarifying questions from both subagents mixed together in tool results, with no way to route its follow-up answers to the correct instance.

A `session_id` argument lets the LLM tag each call with a thread identifier, enabling `_extract_tool_history` to filter by `(tool_name, session_id)` rather than `tool_name` alone.

---

## Design Goals

- The LLM must be aware, per tool, whether the subagent has conversation history — so it sends only the delta on follow-up calls.
- `conversation_mode` (operator config) is the authoritative switch for whether the backend propagates history. The LLM does not set this; it is fixed at app-authoring time.
- `session_id` isolates conversation threads when the same tool is invoked multiple times in a session.
- Preserve full backward-compatibility: existing `propagate_history=True` manifests and `stateless` (default) tools are unchanged.

---

## Use Cases

### UC-1: Single stateful subagent — multi-step task

**Trigger:** User asks the orchestrator: "Assign badge 'Happy 5th Anniversary' to John Smith."

**Behavior:** Orchestrator calls `assign_badge` with `query: "Assign badge … to John Smith"` and `session_id: "badge-task-1"`. Subagent responds: "Please provide EmployeeID." Orchestrator calls `get_employee_id` → gets `123456`. Now the LLM knows `assign_badge` is history-aware (from the tool description), so it calls `assign_badge` again with `query: "123456"` and `session_id: "badge-task-1"`. The backend prepends the prior exchange for that session, and the subagent receives the full thread and completes the task.

**Outcome:** The second call's `query` contains only the delta. The subagent receives the correct full context without duplication.

### UC-2: Multiple parallel research subagents

**Trigger:** User asks the orchestrator to research two separate topics simultaneously. The orchestrator calls `research_tool` twice in parallel: first with `session_id: "research-climate"`, second with `session_id: "research-energy"`.

**Behavior:** Both subagents return clarifying questions. On follow-up, the orchestrator calls each with the same `session_id` used to start that thread. `_extract_tool_history` isolates each session's history by `(tool_name, session_id)`.

**Outcome:** Each subagent receives only its own prior exchanges, not the other's. The orchestrator can correctly route answers.

### UC-3: Stateless tool — no change

**Trigger:** An operator configures a tool without `conversation_mode` (default) or with `conversation_mode: "stateless"`.

**Behavior:** No `session_id` parameter is injected into the schema. No description suffix is added. `_extract_tool_history` is never called.

**Outcome:** Identical to today's behavior. No migration required.

---

## Proposed Design

### `conversation_mode` — two values

```
stateless   (default) — each call is independent; no history or state is propagated
stateful    — backend reconstructs [user, assistant] pairs from the parent's messages and
              prepends them on each call via _extract_tool_history; subagent's
              TOOL_EXECUTION_HISTORY state is threaded back automatically
```

The admin configuring the manifest picks the mode based on what they know about the target DIAL app: `stateful` if it needs prior history sent to it; `stateless` if it handles continuity itself or has no memory.

**Location:** `ConversationMode` enum in `src/quickapp/config/tools/deployment.py`, field on `ContentPropagation`.

`propagate_history=True` remains and continues to trigger the same extraction path — it is not deprecated.

---

### LLM awareness via `enrich_openai_tool_schema`

**What:** For tools with `conversation_mode=stateful`, append a suffix to `function.description` informing the LLM of stateful semantics and delta-only expectations, and inject a `session_id` parameter into the tool schema.

**Where:** `StagedBaseTool.enrich_openai_tool_schema(open_ai_tool)` — no-op base method, overridden in `BaseDeploymentTool`. Wired into `AgentModule.provide_openai_tools` after `_append_default_props`, before serialization. The ordering is intentional: `_append_default_props` only touches `properties` (adds `query` and `attachment_urls`), never `description`, so `enrich_openai_tool_schema` always appends to the original description rather than to something `_append_default_props` may have written.

**Description suffix (informative draft — exact wording TBD):**

> "This tool is a stateful subagent: it maintains conversation history across calls within the same session. On each follow-up call, the backend automatically prepends prior exchanges for that session. **Send only the new information (delta)** in `query` — do not re-summarize prior context. Assign a unique `session_id` at the start of each conversation thread and use the same value for all follow-up calls in that thread."

---

### `session_id` parameter

**What:** An optional string parameter injected into the tool's JSON schema for all tools where `conversation_mode=stateful`.

**Where:** Injected by `BaseDeploymentTool.enrich_openai_tool_schema()` alongside the description suffix.

**Schema shape:**
```json
"session_id": {
  "type": "string",
  "description": "Identifier for this conversation thread. Assign a unique value when starting a new multi-turn exchange with this subagent (e.g. 'research-climate'). Use the same session_id on all follow-up calls for that thread. Use a different session_id to start an independent conversation thread."
}
```

**Who generates `session_id`:** The LLM. The tool description explicitly instructs it to create a unique identifier per thread and use it consistently. The LLM does not need to generate a UUID — any stable string it chooses (e.g., `"badge-task-1"`, `"research-climate"`) is sufficient. Modern instruction-following models reliably maintain such identifiers when clearly instructed.

**`session_id` is NOT sent to the subagent** — it is popped from kwargs in `_run_in_stage_async` before `DialCompletionService.complete_request_async` is called, the same way `attachment_urls` is consumed at the tool layer.

**Fallback when `session_id` is omitted:** If the LLM omits `session_id` on a stateful tool call (e.g., an older model that ignores injected parameters), `_extract_tool_history` falls back to `tool_name`-only filtering — all prior calls to that tool are included regardless of session, which is the same behaviour as `propagate_history=True`.

---

### `_extract_tool_history` changes

Current signature: `_extract_tool_history(tool_name: str)`

New signature: `_extract_tool_history(tool_name: str, session_id: str | None = None)`

**First pass** (collecting TOOL results by `tool_call_id`) — unchanged.

**Second pass** (walking ASSISTANT messages): when `session_id` is provided, only include a tool call if the parsed arguments for that call contain `"session_id": <matching value>`. Tool calls without a matching `session_id` are excluded when filtering is active.

When `session_id` is `None`, falls back to filtering by `tool_name` only — preserving current behavior for `propagate_history=True` callers that do not use `session_id`.

---

### `_run_in_stage_async` changes

At the start of the method, `session_id` is popped from kwargs (consumed here, not forwarded to the subagent). It is then passed as a keyword argument to `_extract_tool_history` when history extraction is triggered by `propagate_history=True` or `conversation_mode=stateful`.

---

## Secondary Fixes

### Empty content with state silently dropped

`_extract_tool_history` previously dropped TOOL messages with empty string content even when `custom_content.state` was present, breaking state threading for subagents that return empty text but carry internal tool-execution history. Fixed:

- First pass: removed `and msg.content` guard; content normalized to `""` for `None`.
- Second pass: guard changed from `if tool_content:` to `if tool_content or tool_custom_content:`.

---

## Out of Scope

**LLM choosing `conversation_mode`.** Issue #88 proposed `conversation_mode` as a runtime tool argument. This design keeps it as operator config: the app author knows at wiring time whether the subagent is stateful. Making the LLM choose adds prompt-engineering fragility — the LLM must correctly infer statefulness from a description and reliably pick the right mode on every call.

**`conversation_summary` mode.** Mentioned in issue #88 as a future extension. Deferred until there is a concrete use case and a summary provider is defined.

**Deprecation of `propagate_history`.** Triggers the same extraction path as `stateful`. Removing it requires a deprecation notice and grace period; deferred.

---

## Configuration / Usage Examples

### Stateful subagent — multi-step task with session isolation

```json
{
  "type": "deployment-tool",
  "deployment": { "endpoint": "assign-badge-app" },
  "content_propagation": {
    "conversation_mode": "stateful"
  }
}
```

The LLM will see `session_id` in the tool schema and call like:
```json
{ "query": "Assign badge 'Happy 5th Anniversary' to John Smith", "session_id": "badge-task-1" }
```

Follow-up (delta only):
```json
{ "query": "123456", "session_id": "badge-task-1" }
```

### Stateless (default)

```json
{
  "type": "deployment-tool",
  "deployment": { "endpoint": "search-tool" }
}
```

No `session_id` in schema. No description suffix. No history extraction.

---

## Migration

### Breaking changes

None. Default is `stateless`; existing manifests without `conversation_mode` behave identically to today.

### Non-breaking additions

Default is `stateless`; existing manifests without `conversation_mode` and `propagate_history=True` callers behave identically to before.

---

## Summary of Changes

| Component | Change |
|---|---|
| `config/tools/deployment.py` | `ConversationMode` enum with `STATELESS` and `STATEFUL`. `ContentPropagation.conversation_mode` documented. |
| `common/staged_base_tool.py` | Add `enrich_openai_tool_schema(open_ai_tool)` extension hook (no-op in base, overridden in `BaseDeploymentTool`). |
| `core/agent/agent_module.py` | `provide_openai_tools`: call `tool.enrich_openai_tool_schema(open_ai_tool)` for every tool after `_append_default_props`. |
| `dial_deployment_tooling/base_deployment_tool.py` | Override `enrich_openai_tool_schema`: inject description suffix and `session_id` parameter when `conversation_mode=STATEFUL`. `_run_in_stage_async`: pop `session_id` from kwargs, pass to `_extract_tool_history`. `_extract_tool_history`: accept `session_id`, filter by `(tool_name, session_id)` when provided. Fix empty-content-with-state edge case. |
| `docs/generated-app-schema.json` | Regenerated after config model changes. |
