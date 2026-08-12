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

- Provide a single `SyntheticToolCallInjector` base class that encapsulates frequency,
  idempotency, position, and message-pair construction.
- Support two injection frequencies with implicit position rules: `ALWAYS`, `APPEND_IF_CHANGED`.
- Enable injection backed by any `StagedBaseTool` (MCP, REST, DIAL deployment) via live execution.
- Make `MessagesTransformer.transform` async so tool calls can be awaited.
- Run all message transformers **after** tool initialization so `StagedBaseTool` instances are
  available when transformers execute.
- Migrate the three existing injectors to the new base with no behavior change.
- Place all generic infrastructure in `common/` with no cross-module dependencies.

---

## Use Cases

### UC-1: File-transfer skill injection (existing, migrated)

**Trigger:** A chat request arrives for an agent with the skills feature enabled.
**Behavior:** The skill content is injected after the first USER message using `APPEND_IF_CHANGED`.
If the content is already present in history with the same hash, injection is skipped. If the skill
content changes (e.g. after an update), a new pair is appended alongside the old one to preserve
conversation history consistency.
**Outcome:** Functionally identical to the prior `ONCE` behavior when content is stable; appends
on content change instead of silently keeping stale content.

### UC-2: Timestamp injection (existing, migrated)

**Trigger:** Every chat request with `features.timestamp` configured.
**Behavior:** A synthetic timestamp tool-call pair is appended at the end of the message list on
every request.
**Outcome:** Identical to the current `_TimestampInjectionTransformer` behavior.

### UC-3: Conditional context notification (existing, migrated)

**Trigger:** A chat request arrives and the set of available context URLs has changed since the
previous turn.
**Behavior:** A synthetic context-notification tool-call pair is appended only when the condition
holds. The condition is evaluated inside `get_content()`, which returns `None` to skip injection.
**Outcome:** Identical to the current `_AttachmentNotificationInjector` behavior.

---

## Proposed Design

### Component 1: `InjectionFrequency` enum

**What:** Enum added to `common/synthetic_injection/_injection_enums.py`.

**Owner:** `common/synthetic_injection/`

**Semantics:**

```python
class InjectionFrequency(StrEnum):
    ALWAYS            = "always"             # always append a new pair at END; accumulates across turns
    APPEND_IF_CHANGED = "append_if_changed"  # inject after first USER on first call; replace in place if content unchanged (re-stamps call_id); append at END if content changed
```

Injection position is implicit in the frequency mode — there is no separate `InjectionPosition`
enum. See Component 2 for the position rules.

**Change:** New files; no existing code modified.

---

### Component 2: `SyntheticToolCallInjector`

**What:** Abstract base class in `common/synthetic_injection/synthetic_tool_call_injector.py`.
Extends `MessagesTransformer`.

**Owner:** `common/synthetic_injection/`

**Semantics:**

Subclasses implement `get_frequency` as an async method and optionally override `should_inject`,
`get_arguments`, and `get_content`:

```python
class SyntheticToolCallInjector(MessagesTransformer, ABC):

    @abstractmethod
    async def get_tool_name(self) -> str: ...

    @abstractmethod
    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency: ...

    async def get_arguments(self) -> dict:
        return {}

    async def should_inject(self, messages: list[Message]) -> bool:
        # Return False to skip injection entirely. Override to add preconditions.
        return True

    @abstractmethod
    async def get_content(self, messages: list[Message]) -> str | None:
        # Return None to skip injection for this turn.
        ...
```

Three overridable methods control `call_id` generation and parsing:

```python
def _make_call_id_prefix(self, tool_name: str, arguments: dict) -> str:
    # stable prefix for a tool+args pair — used for prefix-based history scanning
    # format: {call_id_prefix}t_{hash6(tool_name)}_a_{hash6(args_json)}_
    ...

def make_call_id(self, tool_name, arguments, content, ttl_expiry_seconds=None) -> str:
    # full structured call_id
    # format: {prefix}t_{tool_hash6}_a_{args_hash6}_c_{content_hash6}[_ttl_{expiry:08x}]
    # max length ≤ 45 chars for the default "synth_" prefix — well under OpenAI's 64-char limit
    ...

@staticmethod
def _parse_call_id_ttl_expiry(call_id: str) -> int | None:
    # extracts the Unix expiry from the _ttl_ segment, or returns None
    ...
```

Subclasses (e.g. `_ConfigDrivenToolCallHook`) override `make_call_id` to inject additional
metadata (TTL expiry) into the `call_id` before delegating to `super()`. The tool name is
always hashed, so call_id length is bounded regardless of how long the tool name is.

The base `transform` implementation is a two-stage dispatcher:

1. **Precondition gate**: calls `should_inject(messages)`. Returns messages unchanged if `False`.
   Use this for coarse preconditions (e.g. feature flags, missing config) that are independent
   of content. Conditional injection logic that depends on content belongs in `get_content`.
2. **Frequency dispatch**: calls `get_frequency(messages)` and routes to one of three private
   methods, each responsible for fetching content and determining position:

| Frequency | Private method | Behavior |
|---|---|---|
| `ALWAYS` | `_inject_always` | Fetches content; uses a random `call_id`; appends at **END**. |
| `APPEND_IF_CHANGED` | `_inject_append_if_changed` | Fetches content; computes `call_id` via `make_call_id(tool, args, content)`. If a pair with matching tool+args+content already exists, **replaces it in place** (re-stamps call_id — e.g. updates TTL expiry). If content changed, appends at **END**. On first injection inserts **after the first USER message**. |

All methods return messages unchanged if `get_content()` returns `None`. All fall back to
appending at END when no USER message exists.

**`_inject_at` helper:** both private methods converge on
`_inject_at(messages, idx, tool_name, call_id, arguments, content)`, which:

1. Calls `_enrich_state(call_id, content)` — runs enrichers to build the `state` dict.
2. Calls `_build_pair(tool_name, call_id, arguments, content, state)` — constructs the
   `(ASSISTANT/tool_calls, TOOL)` message pair.
3. Splices the pair into `messages` at position `idx`.

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

| Injector | `get_frequency` | Notes |
|---|---|---|
| `_TimestampInjectionTransformer` | `ALWAYS` | Config check moved to `get_content` returning `None`; appends at END |
| `_InjectFileTransferInstructionTransformer` | `APPEND_IF_CHANGED` | Migrated from `ONCE`; first inject after first USER, appends at END on content change |
| `_AttachmentNotificationInjector` | `ALWAYS` | `should_activate_context_tool` check moved to `should_inject()`; appends at END |

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

### Conditional injector example

Conditional logic belongs in `get_frequency` (to choose `ALWAYS` vs skip via `get_content`
returning `None`) or directly in `get_content`. The example below injects only on the first turn
by returning `None` on subsequent ones:

```python
class FirstTurnGreetingInjector(SyntheticToolCallInjector):
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

`APPEND_IF_CHANGED` naturally handles versioned content: when skill content changes, a new pair
is appended alongside older ones, preserving conversation history. When content is stable, injection
is skipped. No explicit version tracking in arguments is required — the content hash in the
`call_id` handles deduplication automatically:

```python
class VersionedSkillInjector(SyntheticToolCallInjector):
    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        # APPEND_IF_CHANGED: content hash in call_id ensures same content is never re-injected;
        # updated content is appended alongside older pairs to preserve history.
        return InjectionFrequency.APPEND_IF_CHANGED

    async def get_tool_name(self) -> str:
        return "skill_reader"

    async def get_arguments(self) -> dict:
        return {"skill_name": "my_skill"}

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

- `InjectionFrequency`, `SyntheticToolCallInjector`,
  `StagedToolSyntheticInjector` are additive — no existing public API is removed.
- Existing module registrations (`@multiprovider` on `list[MessagesTransformer]`) require no
  changes.

---

## Summary of Changes

### `common/abstract/base_transformer.py`
- `MessagesTransformer.transform` → `async def`

### `common/synthetic_injection/` (new package)
- `__init__.py`
- `_injection_enums.py` — `InjectionFrequency` (`ALWAYS`, `APPEND_IF_CHANGED`)
- `synthetic_tool_call_injector.py` — `SyntheticToolCallInjector`; exposes `make_call_id`, `_make_call_id_prefix`, `_parse_call_id_ttl_expiry` as overridable hooks; `APPEND_IF_CHANGED` replaces existing pairs in place when content is unchanged
- `staged_tool_synthetic_injector.py` — `StagedToolSyntheticInjector`

### `application/_messages_setup.py`
- `setup()` → `async def`, returns `None`, writes `context.messages` directly
- Adds `_RequestContext` dependency

### `application/_request_context_setup.py`
- Removes `_MessagesSetup` dependency and call

### `application/_quick_app_completion.py`
- Adds `await injector.get(_MessagesSetup).setup(request.messages)` after `invoke_initializers()`

### `timestamp_tooling/_timestamp_injection_transformer.py`
- Rewritten as `SyntheticToolCallInjector` subclass (`ALWAYS`)

### `skills/_inject_file_transfer_instruction_transformer.py`
- Rewritten as `SyntheticToolCallInjector` subclass (`APPEND_IF_CHANGED`)

### `attachment_processing/_attachment_notification_injector.py`
- Rewritten as `SyntheticToolCallInjector` subclass (`ALWAYS`); `should_activate_context_tool` moved to `should_inject()`

### Tests
- `test_extract_tool_calls_processor.py` — `setup()` calls become `await`; assertions move to
  `context.messages`
- New unit tests for `SyntheticToolCallInjector` covering all positions and frequencies
