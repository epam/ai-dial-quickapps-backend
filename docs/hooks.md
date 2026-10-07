# Hooks

> [!NOTE]
> Preview feature: requires `ENABLE_PREVIEW_FEATURES=true` and may change without a major version bump.
> Field reference: [CONFIGURATION — Hooks](../CONFIGURATION.md#hooks-configuration).

Hooks let the platform call a configured tool at fixed points of a request, without the model deciding to do so.
Typical use: an agent-memory MCP server whose tools recall memories before the model answers and save the turn
afterwards.

## How hooks work

The top-level `hooks` array lists tool calls. Each hook names a tool (`toolset_name` + `tool_name`, or the exact
function name for DIAL deployment and internal tools), its `arguments`, and an `event`:

| Event | When it fires | What happens to the result |
|---|---|---|
| `on_request_start` | Before the first LLM call of the request | Injected into the history as a synthetic assistant tool-call + tool-result pair, so the model sees it like any earlier tool call |
| `on_completion` | After the turn has finished | Discarded: the hook runs for its side effect only and never reaches the user or the conversation |

Hooks of one event run one after another in manifest order.

### Which tool a hook calls

A hook resolves its tool by the same name the model would use: the toolset name and the tool name joined and
sanitized (`memory_server` + `search_memories` becomes `memory_server_search_memories`). Without `toolset_name`
the `tool_name` is used verbatim. The tool is an ordinary initialized tool, so REST, MCP, DIAL deployment and
internal tools all work, and a tool the model cannot see works too, see
[Tools hidden from the model](#tools-hidden-from-the-model).

If no initialized tool matches, the request reports an initialization error `tool '<name>' not found in
initialized tools` before the model is called.

### Arguments

`arguments` is a JSON-e template rendered against the hook context when the hook fires
([Argument templates](../CONFIGURATION.md#hook-argument-templates)). If an expression cannot be evaluated for
the current request (for example `last_assistant_message.content` on the first turn), that hook is skipped for
the request.

### Keeping injected results in the history (`on_request_start`)

Each request starts again from the history the client sends, and earlier injected pairs are part of it.
`frequency` decides what a new request does about them:

| `frequency` | Behaviour |
|---|---|
| `append_if_changed` (default) | A new pair is added only if the tool returned different content than the pair already in the history for the same tool and arguments |
| `always` | A new pair is added on every request; pairs accumulate across turns |

`refresh_condition` (`{"kind":"ttl","ttl_minutes":N}`) re-runs the hook only once the pair in the history is older
than the TTL. It cannot be combined with templated `arguments`.

### Failure handling

A hook never fails the request. A hook that raises, times out (default 15 s for `on_request_start`, 30 s for
`on_completion`, override with `timeout_seconds`) or cannot render its arguments is logged and skipped, and the
turn continues without its result. Hook calls are shown as debug-level stages, so they do not clutter the default
stage display.

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
- The field is preview-gated. With `ENABLE_PREVIEW_FEATURES` off it is ignored and the tools stay model-visible,
  consistent with no hooks running.
- On the chat-completion branch of `dial-app` the field is ignored with a warning, like `allowed_tools`.
- During a rolling upgrade or after a rollback, a replica running an older version ignores the unknown field and
  exposes the tools to the model.
- Only MCP-based toolsets support it today. REST, DIAL deployment and internal tools are a conditional later
  phase.

### Troubleshooting

| Symptom | Likely cause |
|---|---|
| `tool '...' not found in initialized tools` for a hidden tool | The name is missing from the server's tool list, or from `allowed_tools`; check the warning logged at initialization |
| Manifest rejected: `hidden_from_model entries not present in allowed_tools` | Add the entry to `allowed_tools` or remove it from `hidden_from_model` |
| The model still sees the tool | Preview features are off, or the request ran on an older replica |
| The model asks for the hidden tool and then continues without it | Expected: see [If the model calls a hidden tool anyway](#if-the-model-calls-a-hidden-tool-anyway) |

## See also

- Design: [hook_context_and_lifecycle_events.md](./designs/hook_context_and_lifecycle_events.md),
  [tools_hidden_from_model.md](./designs/tools_hidden_from_model.md)
- Configuration: [CONFIGURATION — Hooks](../CONFIGURATION.md#hooks-configuration)
