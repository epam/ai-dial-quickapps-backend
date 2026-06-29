# Design: External Tools Passthrough

- **Status:** Draft

## Problem

Clients can't contribute their own tools to the agent loop. `request.tools` parameter is ignored.

## Behaviour

- Client-provided `Tool` items in `request.tools` are merged with server tools and forwarded to DIAL Core.
- When the LLM calls a client tool, the call is surfaced in the response (`finish_reason: tool_calls`) instead of being executed server-side.
- Mixed batches (server + client tools in one LLM response): server tools execute first, then external calls are surfaced and the loop stops.
- Client tool names that shadow a server tool name cause `InvalidRequestError`.

## `tools` + `tool_choice` combinations

| `request.tools` | `tool_choice` | LLM calls | Result |
|---|---|---|---|
| absent | any | server tools | normal execution, final answer |
| present | absent / auto / required | external tool | surfaced, loop stops |
| present | absent / auto / required | server tool | normal execution, final answer |
| present | absent / auto / required | mix | server tools execute, external surfaced, loop stops |
| present | `{function: ext_name}` | external tool | surfaced, loop stops |
| present | `{function: server_name}` | server tool | normal execution, final answer |
| any | `"none"` | nothing | final text |

`tool_choice` applies on iteration 1 only. On subsequent turns after client provides tool results, the loop resumes freely.

## Changes

| Component | Change |
|---|---|
| `_RequestContext` | +`extra_tools: list[Tool]` (read-once setter, defaults to `[]`) |
| `_RequestContextSetup.setup_context()` | Extract `Tool` items from `request.tools` (ignore `StaticTool`) |
| `common/_di_types.py` | +`TOOL_NAMES: Annotated[frozenset[str], ...]` |
| `AgentModule` | +`@multiprovider provide_extra_openai_tools()` — serialises extra tools + collision guard |
| `AgentModule` | +`@provider @request_scope provide_tool_names()` → `TOOL_NAMES` |
| `Orchestrator` | Inject `TOOL_NAMES`; partition tool calls; surface client tools via `choice.create_function_tool_call()` |

## Example

**Request:**
```json
{
  "model": "my-app",
  "messages": [{"role": "user", "content": "What is my account balance?"}],
  "tools": [{
    "type": "function",
    "function": {
      "name": "get_account_balance",
      "description": "Returns the balance of the caller's account.",
      "parameters": {"type": "object", "properties": {}, "additionalProperties": false}
    }
  }]
}
```

**Response** (QuickApps stops and surfaces the tool call):
```json
{
  "choices": [{
    "finish_reason": "tool_calls",
    "message": {
      "role": "assistant",
      "tool_calls": [{
          "id": "call_abc",
          "type": "function",
          "function": {"name": "get_account_balance", "arguments": "{}"}
        }]
    }
  }]
}
```

Client executes the tool, sends the result back in a follow-up request (same `tools` array + a `tool` message with `tool_call_id: "call_abc"`). QuickApps resumes the loop and produces the final answer.

## Error Handling: Missing Tool Results

When QuickApps responds with `finish_reason: tool_calls` (external tool calls surfaced), the client
**must** include the corresponding tool results in the follow-up request. Specifically:

- The follow-up `messages` array must contain the assistant message (with `tool_calls`) followed
  immediately by one `role: "tool"` message per surfaced tool call, each carrying the matching
  `tool_call_id`.
- If the client omits tool results (e.g., sends a plain user message instead), QuickApps returns
  `InvalidRequestError` (HTTP 400).

### Validation Rules

| Condition | Error |
|---|---|
| ASSISTANT with external tool_calls followed by USER (no tool results) | "Missing tool result messages for external tool calls: {names}. Expected role 'tool' messages with matching tool_call_ids." |
| TOOL message with `tool_call_id` not matching any preceding ASSISTANT tool_call | "Tool message at index {i}: tool_call_id '{id}' does not match any tool call in the preceding assistant message." |
| Fewer TOOL messages than external tool_calls | "Missing tool results for tool_call_ids: {ids}." |

### Valid Follow-up Shape

```
..., user, assistant(tool_calls=[ext1, ext2]), tool(ext1_result), tool(ext2_result)
```

The request may end with tool messages (QuickApps resumes the loop) or continue
with a user message after all tool results are provided:

```
..., assistant(tool_calls=[ext]), tool(ext_result), user
```

### Changes

| Component | Change |
|---|---|
| `_messages_validator.py` | Allow TOOL messages after ASSISTANT with `tool_calls`; validate `tool_call_id` correspondence |
| `_messages_setup.py` | +`validate_external_tool_results()` — after knowing external tool names, ensures all external tool_call_ids have matching TOOL messages |

## Out of Scope

- `StaticTool` in `request.tools` — unclear semantics as client-provided tools, deferred.
- Per-turn tool overrides — tools are fixed for the request lifetime.
- `parallel_tool_calls` forwarding.
- Multi-turn integration testing for the full external tool round-trip.
