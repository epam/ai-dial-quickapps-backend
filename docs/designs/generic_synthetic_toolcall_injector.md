# Design: Generic Synthetic Tool-Call Injector

- **Status:** Implemented
- **Dependencies:**
  - None

## Problem Statement

Three independent `MessagesTransformer` implementations each inject synthetic tool-call pairs into
the message list at request setup time:

| Transformer | Position | Idempotency |
|---|---|---|
| `_TimestampInjectionTransformer` | append at end | none (always re-injects) |
| `_InjectFileTransferInstructionTransformer` | after first USER message | hardcoded `SYNTHETIC_TOOL_CALL_ID` constant |
| `_AttachmentNotificationInjector` | append at end | condition check on context URLs |

Each class reimplements position splicing, call-id generation, and the `(ASSISTANT/tool_calls, TOOL)`
message pair construction. There is no shared abstraction.

Additionally, there is no mechanism to inject tool calls that require **live execution** (e.g.
calling an MCP tool with predefined arguments to fetch agent memories before the orchestrator loop
starts). The `MessagesTransformer.transform` interface is synchronous, which prevents async tool
calls.

## Design Goals

- Provide a single `SyntheticToolCallInjector` base class that encapsulates position, frequency,
  idempotency, and message-pair construction.
- Support a fixed set of named injection positions.
- Support three injection frequencies: `ONCE`, `ALWAYS`, `REFRESH`.
- Enable injection backed by any `StagedBaseTool` (MCP, REST, DIAL deployment) via live execution.
- Make `MessagesTransformer.transform` async so tool calls can be awaited.
- Run all message transformers **after** tool initialization so `StagedBaseTool` instances are
  available when transformers execute.
- Migrate the three existing injectors to the new base with no behavior change.
- Place all generic infrastructure in `common/` with no cross-module dependencies.

---

## Use Cases

### UC-1: Agent memory retrieval on every turn

**Trigger:** A chat request arrives for an agent wired with an MCP memory server.
**Behavior:** Before the first LLM call, the agent calls the `get_memories` MCP tool with empty
arguments. If a memory tool-call pair already exists in the message history (from a previous turn),
it is replaced with a fresh one containing up-to-date memories. There is always exactly one memory
pair in the conversation.
**Outcome:** The LLM sees current memory contents on every turn without accumulating stale copies.

### UC-2: File-transfer skill injection (existing, migrated)

**Trigger:** A chat request arrives for an agent with the skills feature enabled.
**Behavior:** The skill content is injected after the first USER message exactly once — if the
synthetic call-id is already present in message history, injection is skipped.
**Outcome:** Identical to the current `_InjectFileTransferInstructionTransformer` behavior.

### UC-3: Timestamp injection (existing, migrated)

**Trigger:** Every chat request with `features.timestamp` configured.
**Behavior:** A synthetic timestamp tool-call pair is appended at the end of the message list on
every request.
**Outcome:** Identical to the current `_TimestampInjectionTransformer` behavior.

### UC-4: Conditional context notification (existing, migrated)

**Trigger:** A chat request arrives and the set of available context URLs has changed since the
previous turn.
**Behavior:** A synthetic context-notification tool-call pair is appended only when the condition
holds. The condition is evaluated inside `get_content()`, which returns `None` to skip injection.
**Outcome:** Identical to the current `_AttachmentNotificationInjector` behavior.

---

## Proposed Design

### Component 1: `InjectionPosition` and `InjectionFrequency` enums

**What:** Two enums added to `common/synthetic_injection/_injection_enums.py`.

**Owner:** `common/synthetic_injection/`

**Semantics:**

```python
class InjectionPosition(StrEnum):
    AFTER_FIRST_USER = "after_first_user"  # insert after the first USER message
    BEFORE_LAST_USER = "before_last_user"  # insert before the last USER message
    END              = "end"               # append after all messages

class InjectionFrequency(StrEnum):
    ONCE    = "once"    # inject once; skip if already present in history
    ALWAYS  = "always"  # always append; accumulates across turns
    REFRESH = "refresh" # remove last synthetic pair for this tool, then inject fresh one
```

**Change:** New files; no existing code modified.

---

### Component 2: `SyntheticToolCallInjector`

**What:** Abstract base class in `common/synthetic_injection/synthetic_tool_call_injector.py`.
Extends `MessagesTransformer`.

**Owner:** `common/synthetic_injection/`

**Semantics:**

Subclasses implement `get_frequency` and `get_position` as async methods, receiving the current
message list so they can base their decision on conversation history:

```python
class SyntheticToolCallInjector(MessagesTransformer, ABC):

    @abstractmethod
    async def get_tool_name(self) -> str: ...

    @abstractmethod
    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency: ...

    @abstractmethod
    async def get_position(self, messages: list[Message]) -> InjectionPosition: ...

    async def get_arguments(self) -> dict:
        return {}

    @abstractmethod
    async def get_content(self, messages: list[Message]) -> str | None:
        # Return None to skip injection for this turn.
        ...
```

The base `transform` implementation:

1. **Frequency gate**
   - `ONCE`: checks history for `tool_call_id == _deterministic_call_id(tool_name, arguments)`.
     Skips if found.
   - `REFRESH`: removes the **last** synthetic pair for this tool (identified by `tool_name` and
     `call_id_prefix`), then proceeds to inject a fresh one with a deterministic call_id. Targets
     the last pair regardless of whether its call_id was deterministic or UUID-based, which
     preserves older historical pairs while replacing only the most recent one.
   - `ALWAYS`: proceeds unconditionally.
2. **Content fetch**: calls `get_content(messages)`. Returns messages unchanged if `None`.
   Conditional injection logic belongs here — return `None` to skip.
3. **Pair construction**: builds `(ASSISTANT/tool_calls, TOOL)` message pair.
   - `ONCE` and `REFRESH`: use deterministic `call_id = _deterministic_call_id(tool_name, arguments)`.
   - `ALWAYS`: uses `f"{call_id_prefix}{uuid4().hex[:12]}"`.
4. **Position splice**: inserts the pair at the position returned by `get_position(messages)`.
   - `AFTER_FIRST_USER`: after the first `Role.USER` message; appends at end if no USER message
     exists.
   - `BEFORE_LAST_USER`: before the last `Role.USER` message; appends at end if no USER message
     exists.
   - `END`: appends after all messages.

**Change:** New file. Replaces duplicated logic in all three existing injectors.

---

### Component 3: `StagedToolSyntheticInjector`

**What:** Concrete abstract base in
`common/synthetic_injection/staged_tool_synthetic_injector.py`. Extends
`SyntheticToolCallInjector`. Provides `get_content` by looking up a `StagedBaseTool` by name and
calling `tool.arun()`.

**Owner:** `common/synthetic_injection/`

**Semantics:**

```python
class StagedToolSyntheticInjector(SyntheticToolCallInjector, ABC):
    @inject
    def __init__(self, tools: list[StagedBaseTool]):
        # Keyed by OpenAI function name (sanitized), matching ToolExecutor's lookup strategy.
        self.__tools = _build_tool_dict(tools)

    async def get_content(self, messages: list[Message]) -> str | None:
        tool_name = await self.get_tool_name()
        tool = self.__tools.get(tool_name)
        if tool is None:
            logger.warning("Synthetic injector: tool '%s' not found, skipping", tool_name)
            return None
        result = await tool.arun(**(await self.get_arguments()))
        return result.content if result else None
```

The tool dict is keyed by `tool_config.open_ai_tool.function.name` (the sanitized OpenAI function
name), identical to the strategy used by `ToolExecutor`. `get_tool_name()` must return the same
sanitized name (e.g. `"memory_server_get_memories"`, not `"get_memories"`).

No dependency on `mcp_tooling/` — uses only `StagedBaseTool` from `common/`. Works for any tool
type (MCP, REST, DIAL deployment).

**Change:** New file.

---

### Component 4: Async `MessagesTransformer`

**What:** `transform` becomes `async def` in `common/abstract/base_transformer.py`.

**Owner:** `common/abstract/`

**Semantics:**

```python
class MessagesTransformer(ABC):
    @abstractmethod
    async def transform(self, messages: list[Message]) -> list[Message]: ...
```

`PreInvocationTransformer` is **not** changed — it is not on the async path.

**Change:** One-line change to the abstract method signature. All existing `MessagesTransformer`
subclasses add `async def` to their `transform` override (mechanical, no logic change).

---

### Component 5: `_MessagesSetup` refactor

**What:** `_MessagesSetup.setup()` becomes async, takes ownership of writing to
`_RequestContext.messages`, and returns `None`.

**Owner:** `application/`

**Semantics:**

```python
class _MessagesSetup:
    @inject
    def __init__(self, transformers: list[MessagesTransformer], context: _RequestContext):
        ...

    async def setup(self, messages: list[Message]) -> None:
        messages = self.extract_tool_calls(messages)
        for transformer in self.__transformers:
            messages = await transformer.transform(messages)
        self.__context.messages = messages
```

**Change:** `setup()` is now `async`, returns `None`, and writes `context.messages` directly.
Adds `_RequestContext` as a constructor dependency.

---

### Component 6: Execution order in `_quick_app_completion.py`

**What:** `_MessagesSetup.setup()` is moved to run **after** `invoke_initializers()`.
`_RequestContextSetup` no longer calls `_MessagesSetup`.

**Owner:** `application/`

**Semantics:**

```python
await request_context_setup.setup(request, choice)              # config, api_key, headers
await invoke_initializers(injector, InitializerType.completion)  # tools initialized
await injector.get(_MessagesSetup).setup(request.messages)       # all transformers run
```

All message transformers — including those backed by `StagedBaseTool` — run after tool
initialization, so the full `list[StagedBaseTool]` is available.

**Change:** Move the `_MessagesSetup` call from `_RequestContextSetup` to
`_quick_app_completion.py` after `invoke_initializers()`.

---

### Component 7: Migration of existing injectors

All three existing injectors are rewritten as `SyntheticToolCallInjector` subclasses. Their
custom position, idempotency, and pair-construction logic is deleted.

| Injector | `get_position` | `get_frequency` | Notes |
|---|---|---|---|
| `_TimestampInjectionTransformer` | `END` | `ALWAYS` | Config check moved to `get_content` returning `None` |
| `_InjectFileTransferInstructionTransformer` | `AFTER_FIRST_USER` | `ONCE` | Hardcoded `SYNTHETIC_TOOL_CALL_ID` replaced by base deterministic id |
| `_AttachmentNotificationInjector` | `END` | `ALWAYS` | `should_activate_context_tool` check moved into `get_content` returning `None` |

---

## Out of Scope

- **JSON/manifest-level configuration** of injectors. The current design is code-only (DI
  registration). Config-driven injection can be added in a future pass once the code-level pattern
  is established.
- **Parallel execution of injectors.** Injectors run sequentially. Parallelism can be considered
  if profiling shows it is needed.
- **Hiding stage output for synthetic injections.** `StagedToolSyntheticInjector` calls
  `tool.arun()` which may produce visible stages. Suppressing stage output for background
  injections is deferred.

---

## Configuration / Usage Examples

### Custom MCP-backed injector with `REFRESH`

```python
# my_feature/agent_memory_injector.py
class AgentMemoryInjector(StagedToolSyntheticInjector):
    async def get_position(self, messages: list[Message]) -> InjectionPosition:
        return InjectionPosition.AFTER_FIRST_USER

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return InjectionFrequency.REFRESH

    async def get_tool_name(self) -> str:
        return "memory_server_get_memories"  # sanitized name as registered in StagedBaseTool


# my_feature/agent_memory_module.py
class AgentMemoryModule(Module):
    def configure(self, binder: Binder) -> None:
        binder.bind(AgentMemoryInjector, to=AgentMemoryInjector, scope=request_scope)

    @multiprovider
    def _provide_transformers(
        self, injector: AgentMemoryInjector
    ) -> list[MessagesTransformer]:
        return [injector]
```

Register `AgentMemoryModule` in `app_factory.py` alongside other feature modules.

### Conditional injector example

Conditional logic belongs in `get_frequency` (to choose `ALWAYS` vs skip via `get_content`
returning `None`) or directly in `get_content`. The example below injects only on the first turn
by returning `None` on subsequent ones:

```python
class FirstTurnGreetingInjector(SyntheticToolCallInjector):
    async def get_position(self, messages: list[Message]) -> InjectionPosition:
        return InjectionPosition.AFTER_FIRST_USER

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return InjectionFrequency.ALWAYS

    async def get_tool_name(self) -> str:
        return "greeting_tool"

    async def get_content(self, messages: list[Message]) -> str | None:
        user_count = sum(1 for m in messages if m.role == Role.USER)
        if user_count > 1:
            return None  # skip after the first turn
        return "Hello! Here is your personalised greeting."
```

### Version-aware injection

When injected content changes across app versions but arguments stay the same, include a version
identifier in `get_arguments()`. This gives each version a distinct deterministic call_id, so
`ONCE` naturally accumulates historical versions alongside the new one:

```python
class VersionedSkillInjector(SyntheticToolCallInjector):
    async def get_position(self, messages: list[Message]) -> InjectionPosition:
        return InjectionPosition.AFTER_FIRST_USER

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        # ONCE + versioned arguments: each version gets a distinct deterministic call_id.
        # A new version is injected alongside older ones; the same version is never re-injected.
        return InjectionFrequency.ONCE

    async def get_tool_name(self) -> str:
        return "skill_reader"

    async def get_arguments(self) -> dict:
        return {"skill_name": "my_skill", "version": CURRENT_SKILL_VERSION}

    async def get_content(self, messages: list[Message]) -> str | None:
        return load_skill_content(CURRENT_SKILL_VERSION)
```

---

## Migration

### Breaking changes

- `MessagesTransformer.transform` signature changes from `def` to `async def`. Any external
  implementation of `MessagesTransformer` must add `async`.
- `_MessagesSetup.setup()` return type changes from `list[Message]` to `None`. Call sites that
  used the return value must read `context.messages` instead.

### Non-breaking changes

- `InjectionPosition`, `InjectionFrequency`, `SyntheticToolCallInjector`,
  `StagedToolSyntheticInjector` are additive — no existing public API is removed.
- Existing module registrations (`@multiprovider` on `list[MessagesTransformer]`) require no
  changes.

---

## Summary of Changes

### `common/abstract/base_transformer.py`
- `MessagesTransformer.transform` → `async def`

### `common/synthetic_injection/` (new package)
- `__init__.py`
- `_injection_enums.py` — `InjectionPosition`, `InjectionFrequency`
- `synthetic_tool_call_injector.py` — `SyntheticToolCallInjector`
- `staged_tool_synthetic_injector.py` — `StagedToolSyntheticInjector`

### `application/_messages_setup.py`
- `setup()` → `async def`, returns `None`, writes `context.messages` directly
- Adds `_RequestContext` dependency

### `application/_request_context_setup.py`
- Removes `_MessagesSetup` dependency and call

### `application/_quick_app_completion.py`
- Adds `await injector.get(_MessagesSetup).setup(request.messages)` after `invoke_initializers()`

### `timestamp_tooling/_timestamp_injection_transformer.py`
- Rewritten as `SyntheticToolCallInjector` subclass (`END`, `ALWAYS`)

### `skills/_inject_file_transfer_instruction_transformer.py`
- Rewritten as `SyntheticToolCallInjector` subclass (`AFTER_FIRST_USER`, `ONCE`)

### `attachment_processing/_attachment_notification_injector.py`
- Rewritten as `SyntheticToolCallInjector` subclass (`END`, `ALWAYS`); condition logic moved into `get_content`

### Tests
- `test_extract_tool_calls_processor.py` — `setup()` calls become `await`; assertions move to
  `context.messages`
- New unit tests for `SyntheticToolCallInjector` covering all positions and frequencies
