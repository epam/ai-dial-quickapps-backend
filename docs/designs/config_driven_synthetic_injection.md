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
- Support three content strategies in the first iteration: running a real `StagedBaseTool`, fetching a
  named skill, and injecting a static string.
- Make the content strategy extensible — new variants must be addable without touching existing injector
  code.
- Reuse all injection mechanics from `SyntheticToolCallInjector` and `StagedToolSyntheticInjector`; no
  duplication.
- Gate the feature under `ENABLE_PREVIEW_FEATURES` at both the schema and runtime levels.

---

## Use Cases

### UC-1: Inject memory context from an MCP tool

**Trigger:** An app manifest lists a synthetic injection of kind `tool_call` targeting the
`memory_server_get_memories` tool (MCP toolset `memory_server`, tool `get_memories`) with `frequency:
always`.
**Behavior:** On every request, the injector resolves the final function name
(`sanitize_toolname("memory_server_get_memories")`), calls `tool.arun()`, and injects the resulting
`(ASSISTANT/tool_calls, TOOL)` pair at the end of the message list.
**Outcome:** The LLM receives the agent's memory context before each orchestrator iteration without any
bespoke injector code.

### UC-2: Inject a skill as a one-time instruction

**Trigger:** An app manifest lists a synthetic injection of kind `skill` targeting `my_domain_skill`
with `frequency: append_if_changed`.
**Behavior:** The skill content is fetched via `AgentSkillsProvider`. On first turn it is inserted
after the first USER message. Subsequent turns skip injection unless the skill content changes.
**Outcome:** Operators can attach custom instruction skills to an app without writing a custom
`_InjectFileTransferInstructionTransformer`-style class.

### UC-3: Inject a static note

**Trigger:** An app manifest lists a synthetic injection of kind `static` with a literal content
string and `frequency: append_if_changed`.
**Behavior:** The static string is injected once after the first USER message and never re-injected
(content never changes, so `APPEND_IF_CHANGED` skips all subsequent turns).
**Outcome:** Operators can prepend fixed context notes (e.g. date, tenant ID) in a purely declarative
way.

### UC-4: DIAL Deployment tool injection (no toolset prefix)

**Trigger:** An app manifest lists an injection of kind `tool_call` with `toolset_name` omitted, and
`tool_name` set to the exact final function name of a DIAL Deployment tool.
**Behavior:** The injector uses `tool_name` verbatim (no prefix) to look up the `StagedBaseTool`.
**Outcome:** Injection works for DIAL Deployment and Internal tools whose function names are not
prefixed with a toolset name.

---

## Proposed Design

### Component 1: `SyntheticInjectionConfig` — discriminated union

**What:** A new `SyntheticInjectionConfig` type alias (discriminated union of three variants) in
`config/synthetic_injection.py`. A private `_BaseSyntheticInjectionConfig` holds the four fields
common to all variants; the `kind` discriminator selects the content strategy.

**Owner:** `config/`

**Semantics:**

Base fields shared by all variants:

| Field | Type | Default | Description |
|---|---|---|---|
| `toolset_name` | `str \| None` | `None` | When set, final call name is `sanitize_toolname(f"{toolset_name}_{tool_name}")`. Required for REST API and MCP tools; omit for DIAL Deployment and Internal tools. |
| `tool_name` | `str` | required | Tool name within the toolset, or final OpenAI function name when `toolset_name` is omitted. |
| `arguments` | `dict[str, Any]` | `{}` | Arguments forwarded to the synthetic tool call and (for `tool_call` kind) to `tool.arun()`. |
| `frequency` | `InjectionFrequency` | `append_if_changed` | Injection frequency. |

Variants:

| `kind` | Extra fields | Content source |
|---|---|---|
| `tool_call` | — | Calls `StagedBaseTool.arun(arguments)` for the resolved tool name |
| `skill` | `skill_name: str` | `AgentSkillsProvider.get_skill_content(skill_name)` |
| `static` | `content: str` | Returns `content` directly |

**Change:** New file `config/synthetic_injection.py`.

---

### Component 2: `synthetic_injections` field on `ApplicationConfig`

**What:** A new `PreviewField` on `ApplicationConfig` holding a list of injection configs.

**Owner:** `config/application.py`

**Semantics:**

```python
synthetic_injections: list[SyntheticInjectionConfig] | None = PreviewField(
    default=None,
    description="Config-driven synthetic tool call injections.",
)
```

When `ENABLE_PREVIEW_FEATURES=false`, `_gate_preview_fields` nullifies this field to `None` at
request time and the field is stripped from the published JSON schema. When `None` or empty, the
module provides an empty transformer list.

**Change:** Add field to `ApplicationConfig`; run `make dump_app_schema`.

---

### Component 3: Runtime injector classes

**What:** Three concrete injector classes in
`synthetic_injection_tooling/_config_driven_injectors.py`. All share a common abstract base
`_BaseConfigDrivenInjector(SyntheticToolCallInjector)` that implements `get_tool_name`,
`get_arguments`, and `get_frequency` from the base config fields. Each variant overrides only
`get_content`.

**Owner:** `synthetic_injection_tooling/`

**Semantics:**

```
_BaseConfigDrivenInjector(SyntheticToolCallInjector)  [abstract]
├── get_tool_name()  → sanitize_toolname(f"{toolset_name}_{tool_name}") or tool_name verbatim
├── get_arguments()  → config.arguments
└── get_frequency()  → config.frequency

_ConfigDrivenToolCallInjector(_BaseConfigDrivenInjector, StagedToolSyntheticInjector)
└── get_content()    → inherited from StagedToolSyntheticInjector (calls tool.arun())

_ConfigDrivenSkillInjector(_BaseConfigDrivenInjector)
└── get_content()    → AgentSkillsProvider.get_skill_content(config.skill_name)

_ConfigDrivenStaticInjector(_BaseConfigDrivenInjector)
└── get_content()    → config.content (returns None when blank)
```

`_ConfigDrivenToolCallInjector` inherits from both `_BaseConfigDrivenInjector` and
`StagedToolSyntheticInjector`. Both ultimately extend `SyntheticToolCallInjector`; Python MRO
resolves the diamond cleanly. `_BaseConfigDrivenInjector` is listed first so its implementations
of `get_tool_name`, `get_arguments`, and `get_frequency` take precedence.

No injector class uses `@inject` — all are constructed manually by the module's `@multiprovider`
with explicit arguments.

**Change:** New file `synthetic_injection_tooling/_config_driven_injectors.py`.

---

### Component 4: `SyntheticInjectionModule`

**What:** A new `@preview_module` DI module in
`synthetic_injection_tooling/synthetic_injection_module.py`. Its single `@multiprovider` reads
`app_config.synthetic_injections`, constructs one injector instance per entry (by `kind`), and
contributes them all to `list[MessagesTransformer]`.

**Owner:** `synthetic_injection_tooling/`

**Semantics:**

```python
@preview_module
class SyntheticInjectionModule(Module):

    @multiprovider
    def _provide_transformers(
        self,
        app_config: ApplicationConfig,
        tools: list[StagedBaseTool],
        skills_provider: AgentSkillsProvider,
    ) -> list[MessagesTransformer]:
        injections = app_config.synthetic_injections or []
        result: list[MessagesTransformer] = []
        for entry in injections:
            match entry:
                case ToolCallInjectionConfig():
                    result.append(_ConfigDrivenToolCallInjector(tools, entry))
                case SkillInjectionConfig():
                    result.append(_ConfigDrivenSkillInjector(skills_provider, entry))
                case StaticInjectionConfig():
                    result.append(_ConfigDrivenStaticInjector(entry))
        return result
```

`@preview_module` means the module is not loaded at all when `ENABLE_PREVIEW_FEATURES=false`,
matching the pattern used by `TimestampModule`. When preview is enabled but `synthetic_injections`
is `None` or empty, the multiprovider returns an empty list — no transformers are registered.

**Change:** New files `synthetic_injection_tooling/__init__.py` and
`synthetic_injection_tooling/synthetic_injection_module.py`.

---

### Component 5: Module registration

**What:** `SyntheticInjectionModule` added to the `Injector` in `app_factory.py`.

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

---

## Configuration / Usage Examples

### MCP memory injection (UC-1)

```json
{
  "synthetic_injections": [
    {
      "kind": "tool_call",
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
  "synthetic_injections": [
    {
      "kind": "tool_call",
      "toolset_name": "user_prefs_api",
      "tool_name": "get_preferences",
      "frequency": "append_if_changed"
    }
  ]
}
```

### Skill injection (UC-2)

```json
{
  "synthetic_injections": [
    {
      "kind": "skill",
      "tool_name": "skill_reader",
      "skill_name": "domain_instructions",
      "frequency": "append_if_changed"
    }
  ]
}
```

### Static note (UC-3)

```json
{
  "synthetic_injections": [
    {
      "kind": "static",
      "tool_name": "system_note",
      "content": "You are operating in the EMEA region. All monetary values are in EUR.",
      "frequency": "append_if_changed"
    }
  ]
}
```

### DIAL Deployment tool (no toolset prefix, UC-4)

```json
{
  "synthetic_injections": [
    {
      "kind": "tool_call",
      "tool_name": "My_Summarizer_tool",
      "frequency": "always"
    }
  ]
}
```

---

## Migration

### Breaking changes

None. `synthetic_injections` is a new optional `PreviewField` defaulting to `None`. Existing manifests
are unaffected.

### Non-breaking changes

- `SyntheticInjectionModule` is additive. All existing injectors and DI registrations are unchanged.
- The new `config/synthetic_injection.py` and `synthetic_injection_tooling/` package are purely
  additive.

---

## Summary of Changes

### `config/synthetic_injection.py` — NEW

- `_BaseSyntheticInjectionConfig` — shared base fields (`toolset_name`, `tool_name`, `arguments`,
  `frequency`)
- `ToolCallInjectionConfig` — `kind="tool_call"`
- `SkillInjectionConfig` — `kind="skill"`, adds `skill_name`
- `StaticInjectionConfig` — `kind="static"`, adds `content`
- `SyntheticInjectionConfig` — discriminated union type alias

### `config/application.py` — MODIFIED

- `ApplicationConfig.synthetic_injections: list[SyntheticInjectionConfig] | None` — new `PreviewField`

### `synthetic_injection_tooling/` — NEW package

- `__init__.py`
- `_config_driven_injectors.py` — `_BaseConfigDrivenInjector`, `_ConfigDrivenToolCallInjector`,
  `_ConfigDrivenSkillInjector`, `_ConfigDrivenStaticInjector`
- `synthetic_injection_module.py` — `SyntheticInjectionModule` (`@preview_module`)

### `app_factory.py` — MODIFIED

- Register `SyntheticInjectionModule`

### `docs/generated-app-schema.json` — REGENERATED

- New `synthetic_injections` property (only present when `ENABLE_PREVIEW_FEATURES=true`)
