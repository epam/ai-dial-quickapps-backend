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
`(ASSISTANT/tool_calls, TOOL)` pair immediately before the last USER message.
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
└── ToolCallHookConfig  [kind="tool_call", toolset_name, tool_name, arguments, frequency, refresh_condition]
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
| `refresh_condition` | `RefreshConditionConfig \| None` | `None` | When set, the hook skips the tool call while a prior result is still fresh. See `RefreshConditionConfig` below. |

**`RefreshConditionConfig`** — currently a single-variant discriminated union (extensible):

```
RefreshConditionConfig
└── TTLRefreshCondition  [kind="ttl", ttl_minutes: int]
```

`TTLRefreshCondition` — reuse the last result until the TTL elapses, then re-fetch:

| Field | Type | Default | Description |
|---|---|---|---|
| `kind` | `Literal["ttl"]` | `"ttl"` | Discriminator. |
| `ttl_minutes` | `int` | required | Number of minutes a cached result stays valid. Must be `> 0`. |

Future variants (e.g. `{"kind": "daily"}`) extend the union via `Annotated[Union[...], Field(discriminator="kind")]`.

Future hook variants (e.g. guards at `on_pre_tool_use`, observers at `on_completion`) extend
`_BaseHookConfig` directly with their own fields.

`HookEvent` values:

| Value | Fires at |
|---|---|
| `on_request_start` | After initializers, before the first orchestrator iteration |

Only `on_request_start` is currently available. Additional seams (`on_pre_llm`, `on_pre_tool_use`, `on_post_tool_use`, `on_iteration_end`, `on_completion`) are deferred — they are not in the enum and Pydantic rejects them at validation time.

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

**What:** Two runtime classes in `agent_hooks/_config_driven_hooks.py`,
mirroring the config hierarchy.

**Owner:** `agent_hooks/`

**Semantics:**

```
_BaseConfigDrivenHook(ABC)                           [pure marker — does not commit to any interface]

_ConfigDrivenToolCallHook(_BaseConfigDrivenHook, StagedToolSyntheticInjector)
├── get_tool_name()         → sanitize_toolname(f"{toolset_name}_{tool_name}") or tool_name verbatim
├── get_arguments()         → config.arguments
├── get_frequency(messages) → config.frequency
├── make_call_id(...)       → injects ttl_expiry_seconds when refresh_condition is TTLRefreshCondition
├── should_inject(messages) → checks TTL expiry against existing call_id in history; True if expired/absent
└── get_content(messages)   → overrides StagedToolSyntheticInjector: wraps super().get_content(messages)
                        in try/except; returns the result on success, logs + returns None on exception
```

`_BaseConfigDrivenHook` inherits only from `ABC` — it is a pure marker base that imposes no
interface on future hook variants. Each concrete variant mixes in its own interface
(e.g. `StagedToolSyntheticInjector` for `ToolCallHookConfig`). This keeps future hook kinds
(guards, API calls, static checks) from being locked into `MessagesTransformer`.

`_ConfigDrivenToolCallHook` inherits from both `_BaseConfigDrivenHook` and
`StagedToolSyntheticInjector`. The MRO is:
`_ConfigDrivenToolCallHook → _BaseConfigDrivenHook → StagedToolSyntheticInjector → SyntheticToolCallInjector → MessagesTransformer → ABC`.
`_BaseConfigDrivenHook` is listed first so any overrides it defines in the future take
precedence over `StagedToolSyntheticInjector`.

`_ConfigDrivenToolCallHook` defines an explicit
`__init__(self, tools: list[StagedBaseTool], config: ToolCallHookConfig, enrichers_provider: ProviderOf[list[ToolCallResultEnricher]] | None = None)`
that calls `super().__init__(tools, enrichers_provider)` directly. This is required because
`StagedToolSyntheticInjector.__init__` carries `@inject` — without the override, the injector
library would attempt to wire the class via DI rather than accepting the manually-supplied
arguments from `AgentHooksModule`.

**TTL refresh (`refresh_condition: {kind: "ttl", ttl_minutes: N}`):**

`should_inject` scans conversation history (from the end) for a TOOL message whose `call_id`
starts with `_make_call_id_prefix(tool_name, arguments)`. If no such message exists, injection
proceeds normally. If one is found, `_parse_call_id_ttl_expiry` reads the embedded Unix
timestamp; the hook is skipped while `now < expiry`, and re-runs once `now >= expiry`.

`make_call_id` is overridden to set `ttl_expiry_seconds = int(time.time()) + ttl_minutes * 60`
before delegating to `super().make_call_id(...)`. This stamps the new expiry into the
`call_id` at injection time. Because `APPEND_IF_CHANGED` replaces an existing pair in place
when the content is unchanged, the expiry is refreshed on every re-injection without
duplicating messages in history.

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

**Change:** New file `agent_hooks/_config_driven_hooks.py`.

---

### Component 4: `AgentHooksModule`

**What:** A new `@preview_module` DI module in
`agent_hooks/agent_hooks_module.py`. It routes each hook to the correct
`@multiprovider` list based on `entry.event`, building the skeleton for future event extensions.

**Owner:** `agent_hooks/`

**Event → seam mapping:**

| `HookEvent` | DI list contributed to |
|---|---|
| `on_request_start` | `list[MessagesTransformer]` |

Adding support for a new event means adding one `@multiprovider` method to `AgentHooksModule` and a matching `case` in `_build_on_request_message_transformers`, then uncommenting the corresponding value in `HookEvent`.

**Semantics:**

```python
@preview_module
class AgentHooksModule(Module):

    @multiprovider
    def _provide_messages_transformers(
        self,
        app_config_provider: ProviderOf[ApplicationConfig],
        tools_provider: ProviderOf[list[StagedBaseTool]],
        enrichers_provider: ProviderOf[list[ToolCallResultEnricher]],
    ) -> list[MessagesTransformer]:
        return self._build_on_request_message_transformers(
            app_config_provider, tools_provider, HookEvent.ON_REQUEST_START, enrichers_provider
        )

    @staticmethod
    def _build_on_request_message_transformers(
        app_config_provider: ProviderOf[ApplicationConfig],
        tools_provider: ProviderOf[list[StagedBaseTool]],
        event: HookEvent,
        enrichers_provider: ProviderOf[list[ToolCallResultEnricher]] | None = None,
    ) -> list[MessagesTransformer]:
        result: list[MessagesTransformer] = []
        for entry in app_config_provider.get().hooks or []:
            if entry.event != event:
                continue
            match entry:
                case ToolCallHookConfig():
                    result.append(
                        _ConfigDrivenToolCallHook(tools_provider.get(), entry, enrichers_provider)
                    )
        return result
```

`@preview_module` means the module is not loaded at all when `ENABLE_PREVIEW_FEATURES=false`.
When preview is enabled but `hooks` is `None` or empty, the multiprovider returns an empty list.

**Change:** New files `agent_hooks/__init__.py` and `agent_hooks/agent_hooks_module.py`.

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
- **Additional `HookEvent` seams.** Only `on_request_start` is wired. `on_pre_llm` is additionally
  blocked by `PreInvocationTransformer.transform()` being synchronous while `tool.arun()` is async.
  Other seams (`on_pre_tool_use`, `on_post_tool_use`, `on_iteration_end`, `on_completion`) need new
  orchestrator integration points before they can be enabled.

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

### REST API injection with TTL (re-fetch every hour)

```json
{
  "hooks": [
    {
      "kind": "tool_call",
      "event": "on_request_start",
      "toolset_name": "user_prefs_api",
      "tool_name": "get_preferences",
      "frequency": "append_if_changed",
      "refresh_condition": { "kind": "ttl", "ttl_minutes": 60 }
    }
  ]
}
```

The tool is called on the first request. For the next 60 minutes the cached result is reused
unchanged. Once the TTL elapses the tool is called again; if the result changed it is appended
at the end of history, if unchanged the existing pair is updated in place with a new expiry.

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
- The new `config/hooks.py` and `agent_hooks/` package are purely additive.

---

## Summary of Changes

### `config/hooks.py` — NEW

- `HookEvent` — enum of orchestrator seams; currently only `on_request_start`
- `_BaseHookConfig` — universal fields (`event`, `name`)
- `ToolCallHookConfig(_BaseHookConfig)` — `kind="tool_call"`, adds `toolset_name`, `tool_name`, `arguments`, `frequency`, `refresh_condition`
- `TTLRefreshCondition` — `kind="ttl"`, `ttl_minutes: int`; skip tool call while result is fresh
- `RefreshConditionConfig` — discriminated union type alias (currently single-variant; extensible)
- `HookConfig` — discriminated union type alias (currently a single-variant union; extensible)

### `config/application.py` — MODIFIED

- `ApplicationConfig.hooks: list[HookConfig] | None` — new `PreviewField`

### `agent_hooks/` — NEW package

- `__init__.py`
- `_config_driven_hooks.py` — `_BaseConfigDrivenHook(ABC)` (pure marker), `_ConfigDrivenToolCallHook(_BaseConfigDrivenHook, StagedToolSyntheticInjector)`; adds `make_call_id` (stamps TTL expiry) and `should_inject` (checks TTL) overrides
- `agent_hooks_module.py` — `AgentHooksModule` (`@preview_module`)

### `app_factory.py` — MODIFIED

- Register `AgentHooksModule`

### `docs/generated-app-schema.json` — REGENERATED

- New `hooks` property (only present when `ENABLE_PREVIEW_FEATURES=true`)
