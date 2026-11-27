# Hooks

Hooks run a configured tool at a fixed point of a request, without the model deciding to call it.
This guide describes how that works at runtime. Fields and examples are in
[CONFIGURATION — Hooks](../CONFIGURATION.md#hooks-configuration); the reasoning behind the design is in
[hook_context_and_lifecycle_events.md](./designs/hook_context_and_lifecycle_events.md).

## Request lifecycle

```mermaid
flowchart LR
    A[Request] --> B["on_request_start hooks<br/>(result injected into history)"]
    B --> C[Orchestrator loop<br/>LLM calls and tools]
    C -->|finished normally| D["on_completion hooks<br/>(result discarded;<br/>blocking awaited, background not)"]
    C -->|external tool calls| E[Response closed]
    D --> E
```

| Event | When | Result |
|-------|------|--------|
| `on_request_start` | Before the first LLM call of the request | Injected into the conversation as a synthetic tool-call pair |
| `on_completion` | After the orchestrator loop ended normally. `blocking` hooks finish before the response is closed; `background` hooks do not hold it open (beyond a short hold period) | Discarded; the hook exists for its side effect |

`on_completion` does not fire when the turn ends with external tool calls handed back to the client.

## `on_request_start`

- Each hook runs once per request, in the position of the hooks module in the message-transformer chain.
  It sees the messages as they are at that point: the restored tool history plus pairs injected by earlier
  transformers.
- The tool result is added to the history as an assistant tool call plus a `tool` message, so the model reads
  it as if it had called the tool itself. The call shows the **rendered** arguments.
- The identity of the pair (its call id) is derived from the **unrendered** `arguments`, so it stays the same
  from turn to turn even when the rendered values change. This is what `frequency` relies on:
  - `append_if_changed` (default): an identical result replaces the earlier pair in place, a different
    result is appended as a new pair.
  - `always`: a pair is appended every turn.
  - `refresh_condition` (TTL) finds the earlier pair by that identity, so it works only with static
    `arguments`. Combining it with a template is rejected when the configuration is validated.
- A hook that is skipped (see [Failures](#failures-and-timeouts)) injects nothing; pairs from earlier turns
  stay in place.

## `on_completion`

- Runs after the final answer is streamed. `blocking` hooks (the default) run before the response is closed,
  so per-request MCP sessions are still open and the hook can reuse them.
- `blocking` hooks run **sequentially in manifest order**. The response stays open until they finish, so the
  delay is bounded by the sum of their timeouts.
- The result is not added to the conversation and not stored, so the next turn does not see it.
- A hook with `"execution": "background"` does not delay the response; see [Background hooks](#background-hooks).

### Background hooks

`"execution": "background"` (valid on `on_completion` only; the default is `"blocking"`) is for side effects
nobody waits for, such as saving memory.

- **Not delayed by the hook itself:** the response closes without waiting for the hook to finish. It stays
  open for up to `BACKGROUND_HOOKS_RESPONSE_HOLD_SECONDS` (3 s by default) so the hook's call can reach DIAL Core
  first (a call that starts after the response closed is rejected with 401). A hook that finishes sooner adds
  no more than its own run time.
- **Response delay for slow hooks:** every turn that has a hook slower than the hold period is held for the
  whole period before the response closes. For a long memory save that is the normal case, not a worst case:
  expect the stream to end up to 3 s (by default) after the answer.
- **Order:** background hooks start before blocking ones, so manifest order is not guaranteed between the two
  kinds. Blocking hooks still run in manifest order among themselves.
- **Output:** none. No stage is shown (not even for an error; the one exception is a hook rejected over the
  limit, see Best-effort), nothing is added to the conversation, and
  usage statistics do not include the hook. Failures and timeouts are only logged.
- **Best-effort:** a replica restart loses running hooks (shutdown waits up to
  `BACKGROUND_HOOKS_SHUTDOWN_GRACE_SECONDS` first). At most `BACKGROUND_HOOKS_MAX_CONCURRENT` run per
  process; once more than `BACKGROUND_HOOKS_WARN_THRESHOLD` (40 by default) are running, each newly
  started hook is logged with a warning. A hook over the limit is not run: an error is logged and the response
  shows a failed stage for it, so its side effect (for example a memory save) is known to be lost.
- **No read-your-writes:** a background write of turn N may not be visible to a recall at turn N+1. Keep
  such hooks `blocking`.
- **No sign-in prompt:** the user's request is over, so an MCP toolset that answers 401 or an external-service
  sign-in challenge is not retried; the hook fails and is logged. A 401 can also come back when the result is
  returned although the work finished.
- **Per-request MCP sessions** stay open until the hook ends, bounded by its `timeout_seconds`.

```json
{
  "kind": "tool_call",
  "event": "on_completion",
  "execution": "background",
  "timeout_seconds": 120,
  "toolset_name": "AppMemory",
  "tool_name": "save_memory"
}
```

## Hook context

Arguments are rendered against a read-only snapshot of the conversation. The names and templating syntax are
in [CONFIGURATION — Hook argument templates](../CONFIGURATION.md#hook-argument-templates). Behaviour to know:

- `messages` is a simplified view of the DIAL messages, not the raw objects: `content` is text (multimodal
  parts are reduced to their text, attachments are not exposed), `tool_calls[].arguments` is a parsed object
  rather than a JSON string, and a whitespace-only `content` becomes `""`.
- `messages` is not only the dialog. It also holds the system prompt, tool results and pairs injected by other
  features, so filter by role when you need only the utterances.
- `last_assistant_message` is the last assistant message **without tool calls**, that is, the final answer of a
  previous turn on `on_request_start` and the current answer on `on_completion`.

## Failures and timeouts

A hook never fails the request. Every hook has a timeout (`timeout_seconds`, default 15 s for
`on_request_start`, 30 s for `on_completion`).

| Situation | Outcome |
|-----------|---------|
| Argument template cannot be rendered for this request (for example `last_assistant_message.content` on the first turn) | Hook is skipped for the request |
| Hook exceeds its timeout | Hook is cancelled and skipped, a warning is logged |
| Unexpected error while running the hook | Hook is skipped, the error is logged with a traceback |
| Tool fails and its fallback strategy produces a message (the default) | The tool layer logs `Tool call failed`; for `on_completion` the fallback content is discarded, so a failed write shows up only in that log |

Logs name the hook (`name`, or the tool name) and the event. A successful run logs one `DEBUG` line with the
elapsed time. Arguments and results are never logged.

## Tools hidden from the model

By default every tool a hook can call is also offered to the model. For a tool that only the platform should
drive (for example `prime_memories` and `save_memory`) that is a problem: the model sees the schema, and starts
calling the tool on its own. `hidden_from_model` fixes that on MCP-based toolsets (`mcp`, `dial-mcp`, and the MCP
branch of `dial-app`).

```json
{
  "tool_sets": [
    {
      "type": "dial-app",
      "name": "AppMemory",
      "deployment_id": "memory",
      "transport": "mcp",
      "allowed_tools": ["get_skill", "prime_memories", "save_memory", "search_memories"],
      "hidden_from_model": ["get_skill", "prime_memories", "save_memory"]
    }
  ],
  "hooks": [
    {
      "kind": "tool_call",
      "event": "on_request_start",
      "toolset_name": "AppMemory",
      "tool_name": "prime_memories"
    },
    {
      "kind": "tool_call",
      "event": "on_completion",
      "toolset_name": "AppMemory",
      "tool_name": "save_memory",
      "arguments": { "user_message": { "$eval": "last_user_message.content" } }
    }
  ]
}
```

The model's `tools` contains `AppMemory_search_memories` only. Both hooks run.

### What changes for a hidden tool

| Aspect | Behaviour |
|---|---|
| Model's `tools` payload | The tool is absent |
| `tool_search` catalog and deferral | The tool is absent; it is never deferred and does not count towards `min_tools_for_deferral`. A toolset whose tools are all hidden contributes nothing to discovery |
| Hooks | Unchanged: same `toolset_name` + `tool_name` addressing, same argument templating |
| Same toolset, other tools | Stay visible; one toolset and one MCP session serve both audiences |
| Client-supplied tools | A client tool named like a hidden tool is rejected as a name conflict |

### If the model calls a hidden tool anyway

The synthetic pair injected by an `on_request_start` hook stays in the history with the hidden tool's name, so
the model may imitate it and request the tool. Nothing runs. The model gets an ordinary tool response saying
the tool is not available to it, that the platform calls it automatically, and that it must not call it; the loop
then continues. The event is logged at warning level with the tool name only, and the call still counts towards
the turn's iterations and tool calls.

### Rules and pitfalls

- Entries are raw tool names as the MCP server reports them (the same addressing as `allowed_tools`).
- When `allowed_tools` is set, every `hidden_from_model` entry must be in it, otherwise the manifest is rejected:
  a tool outside `allowed_tools` is dropped before routing and would be lost for the hook too.
- A name the server does not provide is not an error: it is logged as a warning at initialization, and a hook that
  references the tool reports `tool '...' not found in initialized tools`.
- Hiding works by listing. A tool added to the server later is visible to the model unless `allowed_tools` pins
  the set, so set both.
- `None` and an empty list both mean every tool is visible.
- On the chat-completion branch of `dial-app` the field is ignored with a warning, like `allowed_tools`.
- During a rolling upgrade or after a rollback, a replica running an older version ignores the unknown field and
  exposes the tools to the model.
- Only MCP-based toolsets support it today. REST, DIAL deployment and internal tools are a conditional later
  phase.

### Known issues

**Some Claude models disregard the hook result of a hidden tool.** A hook leaves a tool call and its result in the
history, but the tool itself is not in the `tools` payload. Claude Opus 4.6 and 4.7 then treat the result as
unusable: the model answers that it has no such tool, asks the user for the data, or calls a visible tool instead.
The platform delivers the result correctly and the model can quote it when asked, it just does not use it to answer.

- Observed on `anthropic.claude-opus-4-6-v1` and `anthropic.claude-opus-4-7` (hook result used in 0 of 6 direct
  requests, against 6 of 6 when the tool is declared).
- Not observed on Claude Opus 4.8, Opus 5 / 5.5, Sonnet 4.6 / 5 / 5.5, Haiku 5.5 or GPT-5.5. Anthropic's
  documentation does not describe this behaviour, so it may change between model versions.
- Workaround: use one of the models above, or add this paragraph to the application system prompt. With it Opus 4.6
  and 4.7 used the result in 6 of 6 direct requests, and the hook-only integration test passed on Opus 4.6:

  > The conversation may contain tool calls and tool results that the platform executed on your behalf, for tools
  > that are not in your current tool list. Their results are real, current and authoritative: use them to answer
  > instead of saying the tool is unavailable.

### Troubleshooting

| Symptom | Likely cause |
|---|---|
| The model says it has no tool for the data a hook already fetched | Known issue on Claude Opus 4.6 / 4.7: see [Known issues](#known-issues) |
| `tool '...' not found in initialized tools` for a hidden tool | The name is missing from the server's tool list, or from `allowed_tools`; check the warning logged at initialization |
| Manifest rejected: `hidden_from_model entries not present in allowed_tools` | Add the entry to `allowed_tools` or remove it from `hidden_from_model` |
| The model still sees the tool | The request ran on an older replica |
| The model asks for the hidden tool and then continues without it | Expected: see [If the model calls a hidden tool anyway](#if-the-model-calls-a-hidden-tool-anyway) |

## Related

- [CONFIGURATION — Hooks](../CONFIGURATION.md#hooks-configuration) — fields, templates, examples
- [Design: hook context and lifecycle events](./designs/hook_context_and_lifecycle_events.md) — rationale and
  hook-level `condition` and role-filtered message lists (Phase 2)
- [Design: background hooks](./designs/background_hooks.md) — `execution: background`
- [Design: tools hidden from the model](./designs/tools_hidden_from_model.md)
