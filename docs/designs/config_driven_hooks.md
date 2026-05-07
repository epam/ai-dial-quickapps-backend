# Design: Config-Driven Synthetic Tool Call Injection

- **Status:** Approved
- **Dependencies:**
  - [Generic Synthetic Tool-Call Injector](generic_synthetic_toolcall_injector.md)

## Problem Statement

Synthetic tool call injection is code-only. Every new injection requires a new Python class and a DI
module registration. Operators cannot configure injections declaratively in their app manifests — they
must ship code changes to add a synthetic tool call pair to the agent's message history.

A common need in deployed Quick Apps is to pre-populate the agent's context with the result of a
tool call at conversation start (e.g. fetching memories from an MCP server, loading user preferences
from a REST API, or injecting a static system note). Today this requires a new injector class per use
case.

## Design Goals

- Allow operators to define synthetic injections entirely in `ApplicationConfig`, without writing Python
  code.
- Support one content strategy in the first iteration: running a real `StagedBaseTool`.
- Make the content strategy extensible — new variants must be addable without touching existing hook
  code.
- Reuse all injection mechanics from `SyntheticToolCallInjector` and `StagedToolSyntheticInjector`; no
  duplication.

---

## Use Cases

### UC-1: Inject memory context from an MCP tool

**Trigger:** An app manifest lists a hook of kind `tool_call` targeting the
`memory_server_get_memories` tool (MCP toolset `memory_server`, tool `get_memories`) with `frequency:
always`.
**Behavior:** On every request, the hook resolves the final function name
(`sanitize_toolname("memory_server_get_memories")`), calls `tool.arun()`, and injects the resulting
`(ASSISTANT/tool_calls, TOOL)` pair at the end of the message list.
**Outcome:** The LLM receives the agent's memory context before each orchestrator iteration without any
bespoke injector code.

### UC-2: DIAL Deployment tool injection (no toolset prefix)

**Trigger:** An app manifest lists a hook of kind `tool_call` with `toolset_name` omitted, and
`tool_name` set to the exact final function name of a DIAL Deployment tool.
**Behavior:** The hook uses `tool_name` verbatim (no prefix) to look up the `StagedBaseTool`.
**Outcome:** Injection works for DIAL Deployment and Internal tools whose function names are not
prefixed with a toolset name.

---

## Proposed Design

### Component 1: `HookConfig` — discriminated union

**What:** A new `HookConfig` type alias (discriminated union, currently one variant) in
`config/hooks.py`.

**Owner:** `config/`

**Hierarchy:**

```
_BaseHookConfig         [event]
└── ToolCallHookConfig  [kind="tool_call", toolset_name, tool_name, arguments, frequency]
```

`_BaseHookConfig` — the only field universal to any hook:

| Field | Type | Default | Description |
|---|---|---|---|
| `event` | `HookEvent` | required | Orchestrator seam where the hook fires. See `HookEvent` values below. |
| `name` | `str \| None` | `None` | Optional human-readable label for the hook. Used for logging and diagnostics only; no runtime effect. |

`ToolCallHookConfig(_BaseHookConfig)` — resolves a `StagedBaseTool`, calls it, and injects the
resulting `(ASSISTANT/tool_calls, TOOL)` pair into the message history:

| Field | Type | Default | Description |
|---|---|---|---|
| `kind` | `Literal["tool_call"]` | `"tool_call"` | Discriminator. |
| `toolset_name` | `str \| None` | `None` | When set, final call name is `sanitize_toolname(f"{toolset_name}_{tool_name}")`. Required for REST API and MCP tools; omit for DIAL Deployment and Internal tools. |
| `tool_name` | `str` | required | Tool name within the toolset, or final OpenAI function name when `toolset_name` is omitted. |
| `arguments` | `dict[str, Any]` | `{}` | Arguments forwarded to the synthetic tool call and to `tool.arun()`. |
| `frequency` | `InjectionFrequency` | `append_if_changed` | How often to inject. |

Future hook variants (e.g. guards at `on_pre_tool_use`, observers at `on_completion`) extend
`_BaseHookConfig` directly with their own fields.

`HookEvent` values:

| Value | Fires at |
|---|---|
| `on_request_start` | After initializers, before the first orchestrator iteration |
| `on_pre_llm` | Start of each `_run_iteration`, before the LLM call |
| `on_pre_tool_use` | `ToolExecutor.execute`, before `tool.arun` |
| `on_post_tool_use` | After `tool.arun`, before result enrichers |
| `on_iteration_end` | End of each `_run_iteration` |
| `on_completion` | After `Orchestrator.invoke` returns |

**Change:** New file `config/hooks.py`.

---

### Component 2: `hooks` field on `ApplicationConfig`

**What:** A new `PreviewField` on `ApplicationConfig` holding a list of hook configs.

**Owner:** `config/application.py`

**Semantics:**

```python
hooks: list[HookConfig] | None = PreviewField(
    default=None,
    description="Config-driven hooks fired at named orchestrator seams.",
)
```

When `ENABLE_PREVIEW_FEATURES=false`, `_gate_preview_fields` nullifies this field to `None` at
request time and the field is stripped from the published JSON schema. `nullify_preview_fields`
nullifies the `hooks` field itself (not its elements), which is sufficient — once the field is
`None` the list is unreachable regardless of what individual `HookConfig` variants contain.
When `None` or empty, the module provides an empty transformer list.

**Change:** Add field to `ApplicationConfig`; run `make dump_app_schema`.

---

### Component 3: Runtime hook classes

**What:** Two runtime classes in `synthetic_injection_tooling/_config_driven_hooks.py`,
mirroring the config hierarchy.

**Owner:** `synthetic_injection_tooling/`

**Semantics:**

```
_BaseConfigDrivenHook(SyntheticToolCallInjector)     [abstract — for future hook types]

_ConfigDrivenToolCallHook(_BaseConfigDrivenHook, StagedToolSyntheticInjector)
├── get_tool_name()         → sanitize_toolname(f"{toolset_name}_{tool_name}") or tool_name verbatim
├── get_arguments()         → config.arguments
├── get_frequency(messages) → config.frequency
└── get_content(messages)   → overrides StagedToolSyntheticInjector: wraps super().get_content(messages)
                        in try/except; returns the result on success, logs + returns None on exception
```

`_ConfigDrivenToolCallHook` inherits from both `_BaseConfigDrivenHook` and
`StagedToolSyntheticInjector`. Both ultimately extend `SyntheticToolCallInjector`; Python MRO
resolves the diamond cleanly. `_BaseConfigDrivenHook` is listed first so its methods take
precedence over `StagedToolSyntheticInjector`.

`_ConfigDrivenToolCallHook` defines an explicit `__init__(self, tools: list[StagedBaseTool], config: ToolCallHookConfig)`
that calls `super().__init__(tools)` directly. This is required because `StagedToolSyntheticInjector.__init__`
carries `@inject` — without the override, the injector library would attempt to wire the class via
DI rather than accepting the manually-supplied arguments from `AgentHooksModule`.

`StagedBaseTool.arun()` catches exceptions internally and routes them through `FallbackProcessor`.
If a matching fallback strategy is configured on the tool, `arun()` returns a `ToolCallResult` with
an error-message string as content. If no strategy matches, `FallbackProcessor` re-raises the
original exception. Because the tools dict in `StagedToolSyntheticInjector` is name-mangled
(`self.__tools`), `_ConfigDrivenToolCallHook.get_content()` cannot call `arun()` directly — it
delegates to `super().get_content(messages)` wrapped in a try/except: if an exception propagates,
it logs the error and returns `None` to skip injection. Fallback-strategy results (where `arun()`
returned successfully but with error content) are injected as-is; operators who configure fallback
strategies on their tools accept that content.

`_ARUN_SYNTHETIC_CALL_ID` is a fixed probe constant (`"synthetic_injection_probe"`) shared across
all config-driven hooks. This is safe because `get_content()` discards `result.tool_call_id` and
only returns `result.content`; the `call_id` embedded in the injected ASSISTANT/TOOL message pair
is generated independently by `SyntheticToolCallInjector.transform()` (via `uuid4` or content hash).
The constant is used only for perf-timer naming inside `arun`, and transformers run sequentially so
there is no concurrent collision.

No hook class uses `@inject` — all are constructed manually by the module's `@multiprovider`
with explicit arguments.

**Change:** New file `synthetic_injection_tooling/_config_driven_hooks.py`.

---

### Component 4: `AgentHooksModule`

**What:** A new `@preview_module` DI module in
`synthetic_injection_tooling/agent_hooks_module.py`. It routes each hook to the correct
`@multiprovider` list based on `entry.event`, building the skeleton for future event extensions.

**Owner:** `synthetic_injection_tooling/`

**Event → seam mapping (first iteration):**

| `HookEvent` | DI list contributed to | Status |
|---|---|---|
| `on_request_start` | `list[MessagesTransformer]` | ✅ Supported |
| `on_pre_llm` | `list[PreInvocationTransformer]` | ❌ Deferred (`PreInvocationTransformer.transform()` is synchronous; `tool.arun()` is async — bridging requires running in an event loop or restructuring the interface) |
| `on_pre_tool_use` | *(future seam)* | ❌ Deferred |
| `on_post_tool_use` | *(future seam)* | ❌ Deferred |
| `on_iteration_end` | *(future seam)* | ❌ Deferred |
| `on_completion` | *(future seam)* | ❌ Deferred |

Unsupported event+kind combinations log an error and are skipped (resilient degradation).

**Semantics:**

```python
@preview_module
class AgentHooksModule(Module):

    @multiprovider
    def _provide_messages_transformers(
        self,
        app_config: ApplicationConfig,
        tools: list[StagedBaseTool],
    ) -> list[MessagesTransformer]:
        return self._build(app_config, tools, HookEvent.ON_REQUEST_START)

    def _build(
        self,
        app_config: ApplicationConfig,
        tools: list[StagedBaseTool],
        event: HookEvent,
    ) -> list[MessagesTransformer]:
        result = []
        for entry in (app_config.hooks or []):
            if entry.event != event:
                continue
            match entry:
                case ToolCallHookConfig():
                    result.append(_ConfigDrivenToolCallHook(tools, entry))
                case _:
                    logger.error(
                        "Hook type %r is not supported for event %r — skipping",
                        type(entry).__name__,
                        entry.event,
                    )
        return result
```

`@preview_module` means the module is not loaded at all when `ENABLE_PREVIEW_FEATURES=false`.
When preview is enabled but `hooks` is `None` or empty, the multiprovider returns an empty list.
Adding support for a new event requires adding one `@multiprovider` method to `AgentHooksModule` and
one branch in `_build`.

**Change:** New files `synthetic_injection_tooling/__init__.py` and
`synthetic_injection_tooling/agent_hooks_module.py`.

---

### Component 5: Module registration

**What:** `AgentHooksModule` added to the `Injector` in `app_factory.py`.

**Owner:** `app_factory.py`

**Change:** One line added to the module list.

---

## Out of Scope

- **`toolset_id` disambiguation.** Toolset names are assumed unique within an app instance. If two
  toolsets share the same name (which the config schema does not prevent today), the first matching
  tool wins. Explicit toolset-ID scoping is deferred until a concrete collision case arises.
- **`fallback_strategy` per hook config entry.** When `tool.arun()` returns a fallback/error result,
  the current behavior is to log and skip injection. Future work: expose a `fallback_strategy` field
  on `_BaseHookConfig` (e.g. `skip` / `fail_request`) so operators can choose between silently
  skipping a broken injection and hard-failing the request.

- **`should_inject` preconditions per config entry.** Custom preconditions (e.g. inject only on the
  first turn) require code. Config-driven preconditions can be added as an optional `condition` field
  in a future iteration.
- **Content templating.** Arguments and `static` content are treated as literals. Dynamic rendering
  (e.g. Jinja templates) is deferred.
- **Suppressing stage output for injected tool calls.** `StagedToolSyntheticInjector` calls
  `tool.arun()`, which may produce visible stages. Hiding stage output for background injections is
  deferred (tracked in the predecessor design as well).
- **`on_pre_llm` and beyond for `ToolCallHookConfig`.** `on_request_start` is fully wired.
  `on_pre_llm` is blocked by `PreInvocationTransformer.transform()` being synchronous while
  `tool.arun()` is async — bridging requires running in an event loop or restructuring the interface. Remaining events need new orchestrator seams. All are deferred;
  `AgentHooksModule._build` logs an error and skips any unsupported event+kind combination.
- **Structured validation for unsupported `HookEvent` × `kind` combinations.** Currently logged
  and skipped at runtime. Future work: surface this as a structured config validation error
  (Pydantic `@model_validator` → 422 at manifest parse) so operators get early feedback.

---

## Configuration / Usage Examples

### MCP memory injection (UC-1)

```json
{
  "hooks": [
    {
      "kind": "tool_call",
      "event": "on_request_start",
      "toolset_name": "memory_server",
      "tool_name": "get_memories",
      "arguments": { "user_id": "current" },
      "frequency": "always"
    }
  ]
}
```

Resolved call name: `sanitize_toolname("memory_server_get_memories")` = `memory_server_get_memories`.

### REST API injection with toolset prefix

```json
{
  "hooks": [
    {
      "kind": "tool_call",
      "event": "on_request_start",
      "toolset_name": "user_prefs_api",
      "tool_name": "get_preferences",
      "frequency": "append_if_changed"
    }
  ]
}
```

### DIAL Deployment tool (no toolset prefix, UC-2)

```json
{
  "hooks": [
    {
      "kind": "tool_call",
      "event": "on_request_start",
      "tool_name": "My_Summarizer_tool",
      "frequency": "always"
    }
  ]
}
```

---

## Migration

### Breaking changes

None. `hooks` is a new optional `PreviewField` defaulting to `None`. Existing manifests
are unaffected.

### Non-breaking changes

- `AgentHooksModule` is additive. All existing injectors and DI registrations are unchanged.
- The new `config/hooks.py` and `synthetic_injection_tooling/` package are purely additive.

---

## Summary of Changes

### `config/hooks.py` — NEW

- `HookEvent` — enum of orchestrator seams (`on_request_start`, `on_pre_llm`, `on_pre_tool_use`,
  `on_post_tool_use`, `on_iteration_end`, `on_completion`)
- `_BaseHookConfig` — universal fields (`event`, `name`)
- `ToolCallHookConfig(_BaseHookConfig)` — `kind="tool_call"`, adds `toolset_name`, `tool_name`, `arguments`, `frequency`
- `HookConfig` — discriminated union type alias (currently a single-variant union; extensible)

### `config/application.py` — MODIFIED

- `ApplicationConfig.hooks: list[HookConfig] | None` — new `PreviewField`

### `synthetic_injection_tooling/` — NEW package

- `__init__.py`
- `_config_driven_hooks.py` — `_BaseConfigDrivenHook`, `_ConfigDrivenToolCallHook`
- `agent_hooks_module.py` — `AgentHooksModule` (`@preview_module`)

### `app_factory.py` — MODIFIED

- Register `AgentHooksModule`

### `docs/generated-app-schema.json` — REGENERATED

- New `hooks` property (only present when `ENABLE_PREVIEW_FEATURES=true`)
