# Design: Config-Driven Synthetic Tool Call Injection

- **Status:** Draft
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
- Gate the feature under `ENABLE_PREVIEW_FEATURES` at both the schema and runtime levels.

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

`HookEvent` values (from `anthropic-sdk-hooks-applicability.md` § 5):

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
request time and the field is stripped from the published JSON schema. When `None` or empty, the
module provides an empty transformer list.

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
├── get_tool_name()  → sanitize_toolname(f"{toolset_name}_{tool_name}") or tool_name verbatim
├── get_arguments()  → config.arguments
├── get_frequency()  → config.frequency
└── get_content()    → inherited from StagedToolSyntheticInjector (calls tool.arun())
```

`_ConfigDrivenToolCallHook` inherits from both `_BaseConfigDrivenHook` and
`StagedToolSyntheticInjector`. Both ultimately extend `SyntheticToolCallInjector`; Python MRO
resolves the diamond cleanly. `_BaseConfigDrivenHook` is listed first so its methods take
precedence over `StagedToolSyntheticInjector`.

No hook class uses `@inject` — all are constructed manually by the module's `@multiprovider`
with explicit arguments.

**Change:** New file `synthetic_injection_tooling/_config_driven_hooks.py`.

---

### Component 4: `HooksModule`

**What:** A new `@preview_module` DI module in
`synthetic_injection_tooling/hooks_module.py`. It routes each hook to the correct
`@multiprovider` list based on `entry.event`, building the skeleton for future event extensions.

**Owner:** `synthetic_injection_tooling/`

**Event → seam mapping (first iteration):**

| `HookEvent` | DI list contributed to | Status |
|---|---|---|
| `on_request_start` | `list[MessagesTransformer]` | ✅ Supported |
| `on_pre_llm` | `list[PreInvocationTransformer]` | ❌ Deferred (requires async→sync bridge) |
| `on_pre_tool_use` | *(future seam)* | ❌ Deferred |
| `on_post_tool_use` | *(future seam)* | ❌ Deferred |
| `on_iteration_end` | *(future seam)* | ❌ Deferred |
| `on_completion` | *(future seam)* | ❌ Deferred |

Unsupported event+kind combinations raise `ValueError` at module load time (fail fast).

**Semantics:**

```python
@preview_module
class HooksModule(Module):

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
    ) -> list:
        result = []
        for entry in (app_config.hooks or []):
            if entry.event != event:
                continue
            match entry:
                case ToolCallHookConfig():
                    result.append(_ConfigDrivenToolCallHook(tools, entry))
                case _:
                    raise ValueError(
                        f"Hook kind {entry.kind!r} is not supported "
                        f"for event {entry.event!r}"
                    )
        return result
```

`@preview_module` means the module is not loaded at all when `ENABLE_PREVIEW_FEATURES=false`.
When preview is enabled but `hooks` is `None` or empty, the multiprovider returns an empty list.
Adding support for a new event requires adding one `@multiprovider` method to `HooksModule` and
one branch in `_build`.

**Change:** New files `synthetic_injection_tooling/__init__.py` and
`synthetic_injection_tooling/hooks_module.py`.

---

### Component 5: Module registration

**What:** `HooksModule` added to the `Injector` in `app_factory.py`.

**Owner:** `app_factory.py`

**Change:** One line added to the module list.

---

## Out of Scope

- **`toolset_id` disambiguation.** Toolset names are assumed unique within an app instance. If two
  toolsets share the same name (which the config schema does not prevent today), the first matching
  tool wins. Explicit toolset-ID scoping is deferred until a concrete collision case arises.
- **`should_inject` preconditions per config entry.** Custom preconditions (e.g. inject only on the
  first turn) require code. Config-driven preconditions can be added as an optional `condition` field
  in a future iteration.
- **Content templating.** Arguments and `static` content are treated as literals. Dynamic rendering
  (e.g. Jinja templates) is deferred.
- **Suppressing stage output for injected tool calls.** `StagedToolSyntheticInjector` calls
  `tool.arun()`, which may produce visible stages. Hiding stage output for background injections is
  deferred (tracked in the predecessor design as well).
- **`on_pre_llm` and beyond for `ToolCallHookConfig`.** `on_request_start` is fully wired.
  `on_pre_llm` requires an async→sync bridge between `SyntheticToolCallInjector` and
  `PreInvocationTransformer`. Remaining events need new orchestrator seams. All are deferred;
  `HooksModule` raises `ValueError` for any unsupported event at load time.

---

## Configuration / Usage Examples

### MCP memory injection (UC-1)

```json
{
  "hooks": [
    {
      "kind": "tool_call",
      "event": "on_pre_llm",
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
      "event": "on_pre_llm",
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
      "event": "on_pre_llm",
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

- `HooksModule` is additive. All existing injectors and DI registrations are unchanged.
- The new `config/hooks.py` and `synthetic_injection_tooling/` package are purely additive.

---

## Summary of Changes

### `config/hooks.py` — NEW

- `HookEvent` — enum of orchestrator seams (`on_request_start`, `on_pre_llm`, `on_pre_tool_use`,
  `on_post_tool_use`, `on_iteration_end`, `on_completion`)
- `_BaseHookConfig` — universal field (`event`)
- `ToolCallHookConfig(_BaseHookConfig)` — `kind="tool_call"`, adds `toolset_name`, `tool_name`, `arguments`, `frequency`
- `HookConfig` — discriminated union type alias (currently a single-variant union; extensible)

### `config/application.py` — MODIFIED

- `ApplicationConfig.hooks: list[HookConfig] | None` — new `PreviewField`

### `synthetic_injection_tooling/` — NEW package

- `__init__.py`
- `_config_driven_hooks.py` — `_BaseConfigDrivenHook`, `_ConfigDrivenToolCallHook`
- `hooks_module.py` — `HooksModule` (`@preview_module`)

### `app_factory.py` — MODIFIED

- Register `HooksModule`

### `docs/generated-app-schema.json` — REGENERATED

- New `hooks` property (only present when `ENABLE_PREVIEW_FEATURES=true`)
