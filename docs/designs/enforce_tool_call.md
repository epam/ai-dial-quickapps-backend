# Design: Enforce Tool Call

- **Status:** Implemented
- **Dependencies:**
  - None

## Problem Statement

QuickApps does not expose the `tool_choice` parameter to clients. When a client sends a chat completion
request to QuickApps, there is no way to instruct the orchestrator LLM to call a tool on the current
iteration. The underlying DIAL Core API supports `tool_choice` (`"none"`, `"auto"`, `"required"`, or a
named function object), but is not used by QuickApps.

## Design Goals

- **Propagate `tool_choice` from the incoming request to the orchestrator LLM call.** QuickApps accepts
  the parameter and forwards it unchanged - no re-interpretation or filtering.
- **Apply `tool_choice` only on the first orchestrator iteration.** After the first LLM call, the
  orchestrator must revert to its natural behavior (`"auto"`) so subsequent agentic iterations can
  freely decide whether to call tools or produce a final response. Without this, `"required"` would
  trap the agent in an infinite tool-call loop.
- **Follow the existing `response_format` propagation pattern.** Extract from request, store in
  request-scoped context, provide via DI, consume in `_ChatCompletionConfigBuilder`.

---

## Use Cases

### UC-1: Client forces a specific tool call

**Trigger:** Client sends `"tool_choice": {"type": "function", "function": {"name": "web_search"}}`
in the chat completion request.

**Behavior:** On the first orchestrator iteration, the LLM is forced to call `web_search`. On
subsequent iterations the constraint is lifted and the LLM may respond freely.

**Outcome:** The agent always begins by searching the web, then synthesizes the results into a
final response.

### UC-2: Client requires any tool call

**Trigger:** Client sends `"tool_choice": "required"`.

**Behavior:** The first iteration forces the LLM to call at least one tool (model picks which).
Subsequent iterations revert to `"auto"`.

**Outcome:** The agent is guaranteed to use a tool before answering, but retains freedom on tool
selection and on subsequent iterations.

### UC-3: Client suppresses tool calls

**Trigger:** Client sends `"tool_choice": "none"`.

**Behavior:** On the first iteration, the LLM is told not to call any tool and must produce a text
response. The orchestrator loop terminates after one iteration (no tool calls detected).

**Outcome:** The agent responds directly without invoking tools, even if tools are available.

### UC-4: Client requires tool call but no tools are configured

**Trigger:** Client sends `"tool_choice": "required"` to an app with an empty `tool_sets` array.

**Behavior:** QuickApps rejects the request with HTTP 400 before calling the orchestrator LLM.

**Outcome:** Client receives a clear error message: "Cannot enforce tool_choice: no tools are
available. Configure at least one tool set or use tool_choice='auto'."

### UC-5: Default behavior (no `tool_choice`)

**Trigger:** Client omits `tool_choice` from the request.

**Behavior:** No `tool_choice` field is included in the orchestrator payload on any iteration.
The LLM uses its own default (typically `"auto"` when tools are present).

**Outcome:** Identical to current behavior — no regression.

---

## Design

### 1. DI type — `TOOL_CHOICE`

A new annotated type in `common/_di_types.py`:

```python
from aidial_sdk.chat_completion.request import ToolChoice

TOOL_CHOICE = Annotated[ToolChoice | str | None, "TOOL_CHOICE"]
```

`str` is used rather than the SDK's narrower `Literal["auto", "none", "required"]` to avoid
coupling to the SDK's literal set — future values pass through without code changes.

### 2. Request context — extraction and storage

`_RequestContext` gains a `tool_choice` property (same pattern as `response_format`).

`_RequestContextSetup.setup_context()` extracts it from the incoming `Request`:

```python
if isinstance(request, Request) and request.tool_choice is not None:
    context.tool_choice = request.tool_choice
```

No validation is needed beyond what the SDK already provides — the `Request` model validates
the union type via Pydantic.

### 3. DI provider — `AppModule`

`AppModule` adds a request-scoped provider:

```python
@provider
def __provide_tool_choice(self, context: _RequestContext) -> TOOL_CHOICE:
    return context.tool_choice
```

### 4. First-iteration-only semantics — `_ToolChoiceHolder`

`_ChatCompletionConfigBuilder` is NoScope (recreated each iteration), so it cannot track state
across iterations. To ensure `tool_choice` is applied only on the first iteration, a request-scoped
`_ToolChoiceHolder` class is introduced in `agent/_tool_choice_holder.py`.

```python
class _ToolChoiceHolder:
    def __init__(self, tool_choice: TOOL_CHOICE) -> None:
        self._value: ToolChoice | str | None = tool_choice
        self._consumed: bool = False

    def consume(self) -> ToolChoice | str | None:
        if self._consumed:
            return None
        self._consumed = True
        return self._value
```

The holder is registered with `request_scope` in `AgentModule.configure()`. Because it is
request-scoped, it persists across all orchestrator iterations within a single request. The
`consume()` method returns the value on the first call and `None` on all subsequent calls,
giving first-iteration-only semantics without modifying the orchestrator or builder interfaces.

### 5. Consumption — `_ChatCompletionConfigBuilder`

The builder receives `_ToolChoiceHolder` via constructor injection (not `TOOL_CHOICE` directly).
On `build()`, it calls `consume()` and includes the result in the payload if non-None:

```python
tool_choice = self.__tool_choice_holder.consume()
if tool_choice is not None:
    requires_tool = tool_choice == "required" or (
        hasattr(tool_choice, "type") and tool_choice.type == "function"
    )
    if requires_tool and not self.__tools:
        raise InvalidRequestError(...)

    if hasattr(tool_choice, "model_dump"):
        payload["tool_choice"] = tool_choice.model_dump(exclude_none=True, mode="json")
    else:
        payload["tool_choice"] = tool_choice
```

### 6. Validation — `tool_choice` vs available tools

When `tool_choice` demands a tool call (`"required"` or a named function object) but no tools are
available, QuickApps rejects the request with an `InvalidRequestError` (HTTP 400) rather than
forwarding an impossible constraint to the orchestrator LLM.

This covers:
- `"required"` with an empty tool set → 400
- `{"type": "function", "function": {"name": "x"}}` with an empty tool set → 400
- `"auto"` or `"none"` with no tools → passes through (no constraint to enforce)

The validation runs inside `_ChatCompletionConfigBuilder.build()` on the first iteration only
(since `consume()` returns `None` on subsequent iterations).

---

## Out of Scope

- **App-config-level `tool_choice`.** A static `tool_choice` field on `OrchestratorConfig` (set by
  the app builder, applied on every request regardless of client input). This is a reasonable
  future extension but conflates two concerns (client-controlled vs builder-controlled). If needed
  later, it can layer as a default that the client overrides.
- **Per-iteration `tool_choice` control.** Allowing the client to specify different `tool_choice`
  values for different iterations. This would require a fundamentally different API shape.
- **Named function validation.** When `tool_choice` names a specific function, QuickApps does not
  validate that the function exists in the current tool set. The orchestrator LLM (or DIAL Core)
  will return an error if the function is unknown — propagating that error is sufficient.

---

## Configuration / Usage Examples

**Client request with `tool_choice`:**

```json
{
  "messages": [{"role": "user", "content": "What's the weather in London?"}],
  "tool_choice": "required"
}
```

**Client request forcing a named tool:**

```json
{
  "messages": [{"role": "user", "content": "Search for recent AI papers"}],
  "tool_choice": {"type": "function", "function": {"name": "web_search"}}
}
```

**Effect on orchestrator payload (first iteration only):**

```json
{
  "model": "gpt-4o",
  "messages": [...],
  "tools": [...],
  "tool_choice": "required",
  "stream": true
}
```

**Second iteration payload (tool_choice absent):**

```json
{
  "model": "gpt-4o",
  "messages": [...],
  "tools": [...],
  "stream": true
}
```

---

## Migration

No breaking changes. `tool_choice` is optional and defaults to `None`.

## Summary of Changes

### New

| Component | What |
|---|---|
| `common/_di_types.py` | `TOOL_CHOICE` annotated type |
| `agent/_tool_choice_holder.py` | `_ToolChoiceHolder` — request-scoped consume-once holder |
| `application/_request_context.py` | `tool_choice` property on `_RequestContext` |
| `application/_request_context_setup.py` | Extraction from `Request.tool_choice` |
| `application/app_module.py` | `__provide_tool_choice` provider |

### Modified

| Component | What |
|---|---|
| `agent/_chat_completion_config_builder.py` | Inject `_ToolChoiceHolder`, consume and include in payload |
| `agent/agent_module.py` | Bind `_ToolChoiceHolder` with `request_scope` |

---

## Test Plan

**Unit — `_ChatCompletionConfigBuilder`:**
- `tool_choice=None` → payload has no `tool_choice` key.
- `tool_choice="required"` + first build → payload contains `"tool_choice": "required"`.
- `tool_choice="required"` + second build → payload has no `tool_choice` key (consumed).
- `tool_choice=ToolChoice(type="function", function=...)` → payload contains serialized object on first build.
- `tool_choice="none"` → payload contains `"tool_choice": "none"` on first build.

**Unit — `_ToolChoiceHolder`:**
- `consume()` returns value on first call.
- `consume()` returns `None` on subsequent calls.
- `None` input → always returns `None`.

**Unit — validation:**
- `tool_choice="required"` + empty tools list → `InvalidRequestError`.
- `tool_choice=ToolChoice(function name)` + empty tools list → `InvalidRequestError`.
- `tool_choice="none"` + empty tools list → no error.
- `tool_choice="auto"` + empty tools list → no error.
- `tool_choice="required"` + non-empty tools list → no error.

**Unit — `_RequestContextSetup`:**
- Request with `tool_choice` → stored in context.
- Request without `tool_choice` → context value is `None`.

**Integration — agent loop:**
- `tool_choice="required"` forces a tool call on iteration 1; iteration 2 proceeds without constraint.
- `tool_choice="none"` produces a direct text response, loop terminates after one iteration.
- `tool_choice={"type": "function", "function": {"name": "..."}}` forces the named tool on iteration 1.
