# Generic Synthetic Tool-Call Injector — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce `SyntheticToolCallInjector` — a shared abstract base class that consolidates position/frequency/idempotency/pair-construction logic — and migrate the three existing injectors onto it.

**Architecture:** New `common/synthetic_injection/` package holds `InjectionPosition` / `InjectionFrequency` StrEnums, the `SyntheticToolCallInjector` ABC, and `StagedToolSyntheticInjector`. `MessagesTransformer.transform` becomes `async def`; `_MessagesSetup.setup()` becomes async and writes directly to `_RequestContext.messages`; the call is moved after `invoke_initializers()` so tool-backed injectors can access staged tools.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, `injector` DI, `aidial-sdk`, `pytest-asyncio`

---

## File Map

### New files
| File | Responsibility |
|---|---|
| `src/quickapp/common/synthetic_injection/__init__.py` | Package marker |
| `src/quickapp/common/synthetic_injection/_injection_enums.py` | `InjectionPosition`, `InjectionFrequency` StrEnums |
| `src/quickapp/common/synthetic_injection/synthetic_tool_call_injector.py` | `SyntheticToolCallInjector` ABC |
| `src/quickapp/common/synthetic_injection/staged_tool_synthetic_injector.py` | `StagedToolSyntheticInjector` ABC |
| `src/tests/unit_tests/common/test_synthetic_tool_call_injector.py` | Unit tests for the base class (all positions × frequencies) |
| `src/tests/unit_tests/common/test_staged_tool_synthetic_injector.py` | Unit tests for the staged tool base |

### Modified files
| File | Change |
|---|---|
| `src/quickapp/common/abstract/base_transformer.py` | `transform` → `async def` |
| `src/quickapp/agent/_messages_transformers.py` | `_AddSystemPromptTransformer.transform` → `async def` |
| `src/quickapp/application/_messages_setup.py` | `setup()` → `async def`, returns `None`, writes to `_RequestContext.messages`; add `_RequestContext` dep |
| `src/quickapp/application/_request_context_setup.py` | Remove `_MessagesSetup` dependency and call |
| `src/quickapp/application/_quick_app_completion.py` | Add `await injector.get(_MessagesSetup).setup(request.messages)` after `invoke_initializers()` |
| `src/quickapp/timestamp_tooling/_timestamp_injection_transformer.py` | Migrate to `SyntheticToolCallInjector` (`END`, `ALWAYS`); override `call_id_prefix` |
| `src/quickapp/skills/_inject_file_transfer_instruction_transformer.py` | Migrate to `SyntheticToolCallInjector` (`AFTER_FIRST_USER`, `ONCE`) |
| `src/quickapp/attachment_processing/_attachment_notification_injector.py` | Migrate to `SyntheticToolCallInjector` (`END`, `CONDITIONAL`) |
| `src/tests/unit_tests/application_tests/test_extract_tool_calls_processor.py` | Async-ify all calls to `setup()` |
| `src/tests/unit_tests/timestamp_tooling/test_timestamp_injection_transformer.py` | Async-ify; update call_id prefix assertion |
| `src/tests/unit_tests/skills_tests/test_inject_file_transfer_instruction_transformer.py` | Async-ify; update call_id assertion |
| `src/tests/unit_tests/attachment_processing_tests/test_attachment_notification_injector.py` | Async-ify |

---

## Task 1 — Injection enums

**Files:**
- Create: `src/quickapp/common/synthetic_injection/__init__.py`
- Create: `src/quickapp/common/synthetic_injection/_injection_enums.py`

- [ ] **Step 1: Create the package files**

`src/quickapp/common/synthetic_injection/__init__.py` — empty file (package marker).

`src/quickapp/common/synthetic_injection/_injection_enums.py`:

```python
from enum import StrEnum


class InjectionPosition(StrEnum):
    AFTER_FIRST_USER = "after_first_user"  # insert after the first USER message
    BEFORE_LAST_USER = "before_last_user"  # insert before the last USER message
    END = "end"  # append after all messages


class InjectionFrequency(StrEnum):
    ONCE = "once"  # inject once; skip if already present in history
    ALWAYS = "always"  # always append; accumulates across turns
    REFRESH = "refresh"  # remove existing pair if present, then inject fresh one
    CONDITIONAL = "conditional"  # inject only when condition() returns True
```

- [ ] **Step 2: Commit**

```bash
git add src/quickapp/common/synthetic_injection/__init__.py src/quickapp/common/synthetic_injection/_injection_enums.py
git commit -m "feat: add InjectionPosition and InjectionFrequency StrEnums"
```

---

## Task 2 — Make `MessagesTransformer.transform` async + wire `_MessagesSetup`

This task makes the mechanical change to the async interface. All existing transformer behavior is unchanged — just add `async def`.

**Files:**
- Modify: `src/quickapp/common/abstract/base_transformer.py`
- Modify: `src/quickapp/agent/_messages_transformers.py`
- Modify: `src/quickapp/application/_messages_setup.py`
- Modify: `src/quickapp/application/_request_context_setup.py`
- Modify: `src/quickapp/application/_quick_app_completion.py`
- Modify: `src/quickapp/timestamp_tooling/_timestamp_injection_transformer.py` (async def only)
- Modify: `src/quickapp/skills/_inject_file_transfer_instruction_transformer.py` (async def only)
- Modify: `src/quickapp/attachment_processing/_attachment_notification_injector.py` (async def only)
- Modify: `src/tests/unit_tests/application_tests/test_extract_tool_calls_processor.py`
- Modify: `src/tests/unit_tests/timestamp_tooling/test_timestamp_injection_transformer.py`
- Modify: `src/tests/unit_tests/skills_tests/test_inject_file_transfer_instruction_transformer.py`
- Modify: `src/tests/unit_tests/attachment_processing_tests/test_attachment_notification_injector.py`

- [ ] **Step 1: Make `MessagesTransformer.transform` async**

Full replacement for `src/quickapp/common/abstract/base_transformer.py`:

```python
from abc import ABC, abstractmethod

from aidial_sdk.chat_completion import Message


class MessagesTransformer(ABC):
    """Runs once at request setup in _MessagesSetup.setup().

    Mutates the canonical message list that persists across iterations.
    """

    @abstractmethod
    async def transform(self, messages: list[Message]) -> list[Message]: ...


class PreInvocationTransformer(ABC):
    """Runs before every LLM call in AssistantInvoker.__prepare_messages().

    Each transformer is responsible for its own deep-copy strategy — it copies
    only the messages it mutates, leaving the rest as references.  Annotations
    produced by these transformers only exist in the per-invocation copies and
    are never persisted to the canonical message history.
    """

    @abstractmethod
    def transform(self, messages: list[Message]) -> list[Message]: ...
```

- [ ] **Step 2: Add `async def` to all three existing injectors (no logic change)**

In `src/quickapp/timestamp_tooling/_timestamp_injection_transformer.py` — change line 34:
```python
# Before
def transform(self, messages: list[Message]) -> list[Message]:

# After
async def transform(self, messages: list[Message]) -> list[Message]:
```

In `src/quickapp/skills/_inject_file_transfer_instruction_transformer.py` — change line 31:
```python
# Before
def transform(self, messages: list[Message]) -> list[Message]:

# After
async def transform(self, messages: list[Message]) -> list[Message]:
```

In `src/quickapp/attachment_processing/_attachment_notification_injector.py` — change line 31:
```python
# Before
def transform(self, messages: list[Message]) -> list[Message]:

# After
async def transform(self, messages: list[Message]) -> list[Message]:
```

- [ ] **Step 3: Add `async def` to `_AddSystemPromptTransformer`**

In `src/quickapp/agent/_messages_transformers.py` — change line 18:
```python
# Before
def transform(self, messages: list[Message]) -> list[Message]:

# After
async def transform(self, messages: list[Message]) -> list[Message]:
```

- [ ] **Step 4: Refactor `_MessagesSetup` to async**

Full replacement for `src/quickapp/application/_messages_setup.py`:

```python
import copy
import logging
import warnings

from aidial_sdk.chat_completion import Message, Role, ToolCall
from aidial_sdk.utils.pydantic import ExtraAllowModel
from injector import inject

from quickapp.agent.models import TOOL_EXECUTION_HISTORY
from quickapp.application._request_context import _RequestContext
from quickapp.common.abstract.base_transformer import MessagesTransformer

logger = logging.getLogger(__name__)


class ExecutedToolCallDTO(ExtraAllowModel):
    tool_call: ToolCall
    tool_execution_result: Message


@inject
class _MessagesSetup:

    def __init__(
        self,
        transformers: list[MessagesTransformer],
        context: _RequestContext,
    ):
        self.__transformers = transformers
        self.__context = context
        logger.debug(f"Messages transformers: {transformers}")

    async def setup(self, messages: list[Message]) -> None:
        messages = self.extract_tool_calls(messages)
        for transformer in self.__transformers:
            messages = await transformer.transform(messages)
        self.__context.messages = messages

    # ... (keep all existing static/instance methods unchanged below)
```

Keep `_is_legacy_format`, `_extract_legacy_format`, `_extract_message_format`, and `extract_tool_calls` exactly as they are — only the `__init__` signature and `setup()` method change.

- [ ] **Step 5: Remove `_MessagesSetup` from `_RequestContextSetup`**

In `src/quickapp/application/_request_context_setup.py`:

Remove `messages_setup: _MessagesSetup` from `__init__` parameters, remove `self.__messages_setup = messages_setup`, and replace the `context.messages` assignment line:

```python
# Remove this import at the top:
from ._messages_setup import _MessagesSetup

# Updated __init__ — remove messages_setup parameter:
@inject
class _RequestContextSetup:
    def __init__(
        self,
        context_provider: ProviderOf[_RequestContext],
        config_resolver: ConfigResolver,
    ):
        self.__context_provider = context_provider
        self.__config_resolver = config_resolver

    # In setup() — remove this line:
    #   context.messages = self.__messages_setup.setup(request.messages)
    # The setup() body becomes:
    async def setup(
        self, request: Request | ConfigurationRequest, choice: Choice | None = None
    ) -> None:
        context = self.__context_provider.get()
        context.api_key = SecretStr(request.api_key)
        context.bearer = SecretStr(request.bearer_token) if request.bearer_token else None

        context.application_config = self.__resolve_application_config(
            await request.request_dial_application_properties()
        )
        if isinstance(request, Request):
            context.forwarded_headers = extract_x_headers_from_request(request)
            context.client_channel_id = _extract_client_channel_id(context.forwarded_headers)
        if choice:
            context.choice = choice

        if isinstance(request, Request) and request.response_format:
            context.response_format = request.response_format
```

- [ ] **Step 6: Move `_MessagesSetup.setup()` call into `_QuickAppCompletion`**

In `src/quickapp/application/_quick_app_completion.py`, add the import and move the setup call:

```python
# Add import at top (with other local imports):
from ._messages_setup import _MessagesSetup

# In chat_completion(), after invoke_initializers():
async def chat_completion(self, request: Request, response: Response) -> None:
    timer_service = self.__injector.get(PerformanceTimer)
    timer_service.start_period(self.__timer_period_name, level=1)
    with response.create_single_choice() as choice:
        try:
            await self.__injector.get(_RequestContextSetup).setup(request, choice)
            timer_service.add_milestone(self.__timer_period_name, "request context setup")
            await invoke_initializers(self.__injector, InitializerType.completion)
            self.__injector.get(_InitializationErrorHandler).handle_initialization_errors()
            timer_service.add_milestone(self.__timer_period_name, "tools initialization")
            await self.__injector.get(_MessagesSetup).setup(request.messages)
            agent_invoker = self.__injector.get(Orchestrator)  # type: ignore[type-abstract]
            await agent_invoker.invoke()
        except Exception as e:
            self.__handle_exception(choice, e)
        finally:
            # ... (unchanged)
```

- [ ] **Step 7: Async-ify `test_extract_tool_calls_processor.py`**

Every call `msgs_setup.setup(...)` becomes `await msgs_setup.setup(...)`. Every test method becomes `async def`. Add `@pytest.mark.asyncio`. Add `_RequestContext` construction. The class constructor now takes a `_RequestContext` instance:

```python
import pytest
import warnings

from aidial_sdk.chat_completion import CustomContent, FunctionCall, ToolCall
from aidial_sdk.chat_completion.request import Message, Role

from quickapp.agent.models import TOOL_EXECUTION_HISTORY
from quickapp.application._messages_setup import _MessagesSetup
from quickapp.application._request_context import _RequestContext


def make_tool_call(id: str, name: str = "test_tool", arguments: str = "{}") -> ToolCall:
    return ToolCall(id=id, type="function", function=FunctionCall(name=name, arguments=arguments))


def _make_setup(transformers=None) -> tuple[_MessagesSetup, _RequestContext]:
    ctx = _RequestContext()
    setup = _MessagesSetup(transformers or [], ctx)
    return setup, ctx


class TestExtractToolCallsFromStateProcessor:

    @pytest.mark.asyncio
    async def test_empty_messages_returns_empty(self):
        msgs_setup, ctx = _make_setup()
        await msgs_setup.setup([])
        assert ctx.messages == []

    @pytest.mark.asyncio
    async def test_messages_without_state_unchanged(self):
        msgs_setup, ctx = _make_setup()
        messages = [
            Message(role=Role.USER, content="hello"),
            Message(role=Role.ASSISTANT, content="hi there"),
        ]
        await msgs_setup.setup(messages)
        assert len(ctx.messages) == 2
        assert ctx.messages[0].role == Role.USER
        assert ctx.messages[1].role == Role.ASSISTANT

    @pytest.mark.asyncio
    async def test_message_without_tool_history_unchanged(self):
        msgs_setup, ctx = _make_setup()
        messages = [
            Message(
                role=Role.ASSISTANT,
                content="response",
                custom_content=CustomContent(state={"other_key": "value"}),
            )
        ]
        await msgs_setup.setup(messages)
        assert len(ctx.messages) == 1
        assert ctx.messages[0].content == "response"

    @pytest.mark.asyncio
    async def test_new_format_single_tool_call(self):
        msgs_setup, ctx = _make_setup()
        tc = make_tool_call("tc-1", "my_tool")

        tool_history = [
            {"role": "assistant", "content": "", "tool_calls": [tc.model_dump(mode="json")]},
            {"role": "tool", "content": "tool output", "tool_call_id": "tc-1"},
        ]

        messages = [
            Message(
                role=Role.ASSISTANT,
                content="final response",
                custom_content=CustomContent(state={TOOL_EXECUTION_HISTORY: tool_history}),
            )
        ]

        await msgs_setup.setup(messages)

        assert len(ctx.messages) == 3
        assert ctx.messages[0].role == Role.ASSISTANT
        assert len(ctx.messages[0].tool_calls) == 1
        assert ctx.messages[0].tool_calls[0].id == "tc-1"
        assert ctx.messages[1].role == Role.TOOL
        assert ctx.messages[1].content == "tool output"
        assert ctx.messages[1].tool_call_id == "tc-1"
        assert ctx.messages[2].role == Role.ASSISTANT
        assert ctx.messages[2].content == "final response"

    @pytest.mark.asyncio
    async def test_new_format_parallel_tool_calls_preserved(self):
        msgs_setup, ctx = _make_setup()
        tc1 = make_tool_call("tc-1", "tool_a")
        tc2 = make_tool_call("tc-2", "tool_b")

        tool_history = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [tc1.model_dump(mode="json"), tc2.model_dump(mode="json")],
            },
            {"role": "tool", "content": "output a", "tool_call_id": "tc-1"},
            {"role": "tool", "content": "output b", "tool_call_id": "tc-2"},
        ]

        messages = [
            Message(
                role=Role.ASSISTANT,
                content="done",
                custom_content=CustomContent(state={TOOL_EXECUTION_HISTORY: tool_history}),
            )
        ]

        await msgs_setup.setup(messages)

        assert len(ctx.messages) == 4
        assert ctx.messages[0].role == Role.ASSISTANT
        assert len(ctx.messages[0].tool_calls) == 2
        assert ctx.messages[0].tool_calls[0].id == "tc-1"
        assert ctx.messages[0].tool_calls[1].id == "tc-2"
        assert ctx.messages[1].role == Role.TOOL
        assert ctx.messages[1].tool_call_id == "tc-1"
        assert ctx.messages[2].role == Role.TOOL
        assert ctx.messages[2].tool_call_id == "tc-2"
        assert ctx.messages[3].role == Role.ASSISTANT
        assert ctx.messages[3].content == "done"

    @pytest.mark.asyncio
    async def test_new_format_multiple_iterations(self):
        msgs_setup, ctx = _make_setup()
        tc1 = make_tool_call("tc-1", "tool_a")
        tc2 = make_tool_call("tc-2", "tool_b")

        tool_history = [
            {"role": "assistant", "content": "", "tool_calls": [tc1.model_dump(mode="json")]},
            {"role": "tool", "content": "output 1", "tool_call_id": "tc-1"},
            {"role": "assistant", "content": "", "tool_calls": [tc2.model_dump(mode="json")]},
            {"role": "tool", "content": "output 2", "tool_call_id": "tc-2"},
        ]

        messages = [
            Message(
                role=Role.ASSISTANT,
                content="final",
                custom_content=CustomContent(state={TOOL_EXECUTION_HISTORY: tool_history}),
            )
        ]

        await msgs_setup.setup(messages)

        assert len(ctx.messages) == 5
        assert ctx.messages[0].role == Role.ASSISTANT
        assert ctx.messages[0].tool_calls[0].id == "tc-1"
        assert ctx.messages[1].role == Role.TOOL
        assert ctx.messages[2].role == Role.ASSISTANT
        assert ctx.messages[2].tool_calls[0].id == "tc-2"
        assert ctx.messages[3].role == Role.TOOL
        assert ctx.messages[4].role == Role.ASSISTANT
        assert ctx.messages[4].content == "final"

    @pytest.mark.asyncio
    async def test_legacy_format_backward_compatibility(self):
        msgs_setup, ctx = _make_setup()
        tc = make_tool_call("tc-1", "my_tool")

        legacy_history = [
            {
                "tool_call": tc.model_dump(mode="json"),
                "tool_execution_result": {
                    "role": "tool",
                    "content": "output",
                    "tool_call_id": "tc-1",
                },
            }
        ]

        messages = [
            Message(
                role=Role.ASSISTANT,
                content="done",
                custom_content=CustomContent(state={TOOL_EXECUTION_HISTORY: legacy_history}),
            )
        ]

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            await msgs_setup.setup(messages)
            deprecation_warnings = [
                x
                for x in w
                if issubclass(x.category, DeprecationWarning)
                and "tool_execution_history" in str(x.message).lower()
            ]
            assert len(deprecation_warnings) == 1
            assert "deprecated" in str(deprecation_warnings[0].message).lower()

        assert len(ctx.messages) == 3
        assert ctx.messages[0].role == Role.ASSISTANT
        assert ctx.messages[0].tool_calls[0].id == "tc-1"
        assert ctx.messages[1].role == Role.TOOL
        assert ctx.messages[2].role == Role.ASSISTANT

    @pytest.mark.asyncio
    async def test_tool_history_removed_from_final_message_state(self):
        msgs_setup, ctx = _make_setup()
        tc = make_tool_call("tc-1", "my_tool")

        tool_history = [
            {"role": "assistant", "content": "", "tool_calls": [tc.model_dump(mode="json")]},
            {"role": "tool", "content": "output", "tool_call_id": "tc-1"},
        ]

        messages = [
            Message(
                role=Role.ASSISTANT,
                content="done",
                custom_content=CustomContent(
                    state={TOOL_EXECUTION_HISTORY: tool_history, "other_key": "preserved"}
                ),
            )
        ]

        await msgs_setup.setup(messages)

        final_msg = ctx.messages[-1]
        assert final_msg.custom_content is not None
        assert final_msg.custom_content.state is not None
        assert TOOL_EXECUTION_HISTORY not in final_msg.custom_content.state
        assert final_msg.custom_content.state.get("other_key") == "preserved"

    def test_is_legacy_format_detection(self):
        legacy = [{"tool_call": {}, "tool_execution_result": {}}]
        assert _MessagesSetup._is_legacy_format(legacy) is True

        new = [{"role": "assistant", "content": ""}]
        assert _MessagesSetup._is_legacy_format(new) is False

        assert _MessagesSetup._is_legacy_format([]) is False
```

- [ ] **Step 8: Async-ify `test_timestamp_injection_transformer.py`**

Every `result = transformer.transform(messages)` becomes `result = await transformer.transform(messages)`. Every test method becomes `async def`. Add `import pytest` and `@pytest.mark.asyncio`. No other logic changes. The `call_id.startswith(SYNTHETIC_TIMESTAMP_CALL_PREFIX)` assertion stays valid because `_TimestampInjectionTransformer` still uses its own `call_id` prefix (task 5 handles the migration).

- [ ] **Step 9: Async-ify `test_inject_file_transfer_instruction_transformer.py`**

Every `result = transformer.transform(messages)` becomes `result = await transformer.transform(messages)`. Every test method becomes `async def`. Add `import pytest` and `@pytest.mark.asyncio`.

- [ ] **Step 10: Async-ify `test_attachment_notification_injector.py`**

Every `result = injector.transform(messages)` becomes `result = await injector.transform(messages)`. Every test method becomes `async def`. Add `import pytest` and `@pytest.mark.asyncio`.

- [ ] **Step 11: Run tests**

```bash
source .venv/bin/activate && make test
```

Expected: all tests pass (no behavior changes, only async signatures).

- [ ] **Step 12: Commit**

```bash
git add src/quickapp/common/abstract/base_transformer.py \
        src/quickapp/agent/_messages_transformers.py \
        src/quickapp/application/_messages_setup.py \
        src/quickapp/application/_request_context_setup.py \
        src/quickapp/application/_quick_app_completion.py \
        src/quickapp/timestamp_tooling/_timestamp_injection_transformer.py \
        src/quickapp/skills/_inject_file_transfer_instruction_transformer.py \
        src/quickapp/attachment_processing/_attachment_notification_injector.py \
        src/tests/unit_tests/application_tests/test_extract_tool_calls_processor.py \
        src/tests/unit_tests/timestamp_tooling/test_timestamp_injection_transformer.py \
        src/tests/unit_tests/skills_tests/test_inject_file_transfer_instruction_transformer.py \
        src/tests/unit_tests/attachment_processing_tests/test_attachment_notification_injector.py
git commit -m "refactor: make MessagesTransformer.transform async; move _MessagesSetup after invoke_initializers"
```

---

## Task 3 — `SyntheticToolCallInjector` base class (TDD)

**Files:**
- Create: `src/quickapp/common/synthetic_injection/synthetic_tool_call_injector.py`
- Create: `src/tests/unit_tests/common/test_synthetic_tool_call_injector.py`

- [ ] **Step 1: Write failing tests**

Create `src/tests/unit_tests/common/test_synthetic_tool_call_injector.py`:

```python
import pytest
from aidial_sdk.chat_completion import Message, Role

from quickapp.common.synthetic_injection._injection_enums import (
    InjectionFrequency,
    InjectionPosition,
)
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    SyntheticToolCallInjector,
)


# ---------------------------------------------------------------------------
# Minimal concrete implementations for testing
# ---------------------------------------------------------------------------

class _AlwaysEndInjector(SyntheticToolCallInjector):
    position = InjectionPosition.END
    frequency = InjectionFrequency.ALWAYS

    async def get_tool_name(self) -> str:
        return "test_tool"

    async def get_content(self, messages: list[Message]) -> str | None:
        return "test content"


class _OnceAfterFirstUserInjector(SyntheticToolCallInjector):
    position = InjectionPosition.AFTER_FIRST_USER
    frequency = InjectionFrequency.ONCE

    async def get_tool_name(self) -> str:
        return "once_tool"

    async def get_content(self, messages: list[Message]) -> str | None:
        return "once content"


class _RefreshBeforeLastUserInjector(SyntheticToolCallInjector):
    position = InjectionPosition.BEFORE_LAST_USER
    frequency = InjectionFrequency.REFRESH

    async def get_tool_name(self) -> str:
        return "refresh_tool"

    async def get_content(self, messages: list[Message]) -> str | None:
        return "refreshed content"


class _ConditionalEndInjector(SyntheticToolCallInjector):
    position = InjectionPosition.END
    frequency = InjectionFrequency.CONDITIONAL

    def __init__(self, condition_result: bool = True):
        self._condition_result = condition_result

    async def get_tool_name(self) -> str:
        return "cond_tool"

    def condition(self, messages: list[Message]) -> bool:
        return self._condition_result

    async def get_content(self, messages: list[Message]) -> str | None:
        return "cond content"


class _NullContentInjector(SyntheticToolCallInjector):
    position = InjectionPosition.END
    frequency = InjectionFrequency.ALWAYS

    async def get_tool_name(self) -> str:
        return "null_tool"

    async def get_content(self, messages: list[Message]) -> str | None:
        return None


# ---------------------------------------------------------------------------
# Pair structure helpers
# ---------------------------------------------------------------------------

def _user(content: str = "hi") -> Message:
    return Message(role=Role.USER, content=content)


def _assert_synthetic_pair(
    messages: list[Message], assistant_idx: int, tool_name: str, content: str
) -> str:
    """Assert that messages[assistant_idx:assistant_idx+2] is a valid synthetic pair.
    Returns the call_id."""
    assistant = messages[assistant_idx]
    tool = messages[assistant_idx + 1]

    assert assistant.role == Role.ASSISTANT
    assert assistant.tool_calls is not None and len(assistant.tool_calls) == 1
    assert assistant.tool_calls[0].function.name == tool_name
    call_id = assistant.tool_calls[0].id
    assert call_id.startswith("synthetic_"), f"call_id should start with 'synthetic_', got {call_id!r}"

    assert tool.role == Role.TOOL
    assert tool.tool_call_id == call_id
    assert tool.content == content

    return call_id


# ---------------------------------------------------------------------------
# Tests: ALWAYS + END
# ---------------------------------------------------------------------------

class TestAlwaysEnd:
    @pytest.mark.asyncio
    async def test_appends_pair_at_end(self):
        injector = _AlwaysEndInjector()
        messages = [_user("hello")]

        result = await injector.transform(messages)

        assert len(result) == 3
        assert result[0] is messages[0]
        _assert_synthetic_pair(result, 1, "test_tool", "test content")

    @pytest.mark.asyncio
    async def test_accumulates_on_multiple_calls(self):
        injector = _AlwaysEndInjector()
        messages = [_user("hello")]

        result1 = await injector.transform(messages)
        result2 = await injector.transform(result1)

        # ALWAYS: two pairs accumulated (3 + 2 = 5)
        assert len(result2) == 5

    @pytest.mark.asyncio
    async def test_empty_messages_appends_pair(self):
        injector = _AlwaysEndInjector()
        result = await injector.transform([])
        assert len(result) == 2
        _assert_synthetic_pair(result, 0, "test_tool", "test content")


# ---------------------------------------------------------------------------
# Tests: ONCE + AFTER_FIRST_USER
# ---------------------------------------------------------------------------

class TestOnceAfterFirstUser:
    @pytest.mark.asyncio
    async def test_injects_after_first_user(self):
        injector = _OnceAfterFirstUserInjector()
        messages = [_user("first"), Message(role=Role.ASSISTANT, content="reply"), _user("second")]

        result = await injector.transform(messages)

        assert len(result) == 5
        assert result[0].role == Role.USER
        assert result[0].content == "first"
        _assert_synthetic_pair(result, 1, "once_tool", "once content")
        assert result[3].role == Role.ASSISTANT
        assert result[4].role == Role.USER
        assert result[4].content == "second"

    @pytest.mark.asyncio
    async def test_skips_if_already_present(self):
        injector = _OnceAfterFirstUserInjector()
        messages = [_user("hello")]

        result1 = await injector.transform(messages)
        assert len(result1) == 3

        result2 = await injector.transform(result1)
        assert len(result2) == 3  # unchanged

    @pytest.mark.asyncio
    async def test_uses_deterministic_call_id(self):
        injector = _OnceAfterFirstUserInjector()
        result1 = await injector.transform([_user("hi")])
        result2 = await injector.transform([_user("hi")])

        # Same deterministic call_id on both fresh runs
        id1 = result1[1].tool_calls[0].id
        id2 = result2[1].tool_calls[0].id
        assert id1 == id2
        assert id1 == "synthetic_once_once_tool"

    @pytest.mark.asyncio
    async def test_no_user_message_appends_at_end(self):
        injector = _OnceAfterFirstUserInjector()
        messages = [Message(role=Role.SYSTEM, content="sys")]

        result = await injector.transform(messages)

        assert len(result) == 3
        assert result[0].role == Role.SYSTEM
        _assert_synthetic_pair(result, 1, "once_tool", "once content")


# ---------------------------------------------------------------------------
# Tests: REFRESH + BEFORE_LAST_USER
# ---------------------------------------------------------------------------

class TestRefreshBeforeLastUser:
    @pytest.mark.asyncio
    async def test_injects_before_last_user(self):
        injector = _RefreshBeforeLastUserInjector()
        messages = [_user("hello")]

        result = await injector.transform(messages)

        assert len(result) == 3
        _assert_synthetic_pair(result, 0, "refresh_tool", "refreshed content")
        assert result[2].role == Role.USER
        assert result[2].content == "hello"

    @pytest.mark.asyncio
    async def test_removes_existing_and_reinjects(self):
        injector = _RefreshBeforeLastUserInjector()
        messages = [_user("hello")]

        result1 = await injector.transform(messages)
        assert len(result1) == 3

        result2 = await injector.transform(result1)
        # Old pair removed, new pair inserted → still 3 total (not 5)
        assert len(result2) == 3
        # The pair is still valid
        _assert_synthetic_pair(result2, 0, "refresh_tool", "refreshed content")

    @pytest.mark.asyncio
    async def test_no_user_message_appends_at_end(self):
        injector = _RefreshBeforeLastUserInjector()
        messages = [Message(role=Role.SYSTEM, content="sys")]

        result = await injector.transform(messages)

        assert len(result) == 3
        assert result[0].role == Role.SYSTEM
        _assert_synthetic_pair(result, 1, "refresh_tool", "refreshed content")


# ---------------------------------------------------------------------------
# Tests: CONDITIONAL + END
# ---------------------------------------------------------------------------

class TestConditionalEnd:
    @pytest.mark.asyncio
    async def test_injects_when_condition_true(self):
        injector = _ConditionalEndInjector(condition_result=True)
        messages = [_user("hello")]

        result = await injector.transform(messages)

        assert len(result) == 3
        _assert_synthetic_pair(result, 1, "cond_tool", "cond content")

    @pytest.mark.asyncio
    async def test_skips_when_condition_false(self):
        injector = _ConditionalEndInjector(condition_result=False)
        messages = [_user("hello")]

        result = await injector.transform(messages)

        assert result is messages

    @pytest.mark.asyncio
    async def test_uses_random_call_id(self):
        injector = _ConditionalEndInjector(condition_result=True)
        messages = [_user("hi")]

        result1 = await injector.transform(messages)
        result2 = await injector.transform(messages)

        id1 = result1[1].tool_calls[0].id
        id2 = result2[1].tool_calls[0].id
        assert id1 != id2  # random each time


# ---------------------------------------------------------------------------
# Tests: get_content returns None
# ---------------------------------------------------------------------------

class TestNullContent:
    @pytest.mark.asyncio
    async def test_returns_messages_unchanged_when_content_is_none(self):
        injector = _NullContentInjector()
        messages = [_user("hello")]

        result = await injector.transform(messages)

        assert result is messages


# ---------------------------------------------------------------------------
# Tests: custom call_id_prefix
# ---------------------------------------------------------------------------

class TestCustomCallIdPrefix:
    @pytest.mark.asyncio
    async def test_custom_prefix_applied(self):
        class _PrefixedInjector(SyntheticToolCallInjector):
            position = InjectionPosition.END
            frequency = InjectionFrequency.ALWAYS
            call_id_prefix = "my_prefix_"

            async def get_tool_name(self) -> str:
                return "prefixed_tool"

            async def get_content(self, messages: list[Message]) -> str | None:
                return "content"

        injector = _PrefixedInjector()
        result = await injector.transform([_user("hi")])
        call_id = result[1].tool_calls[0].id
        assert call_id.startswith("my_prefix_")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && make test ARGS="-k test_synthetic_tool_call_injector -x"
```

Expected: `ModuleNotFoundError` — `synthetic_tool_call_injector` does not exist yet.

- [ ] **Step 3: Implement `SyntheticToolCallInjector`**

Create `src/quickapp/common/synthetic_injection/synthetic_tool_call_injector.py`:

```python
import logging
from abc import ABC, abstractmethod
from uuid import uuid4

from aidial_sdk.chat_completion import Message, Role
from aidial_sdk.chat_completion.request import FunctionCall, ToolCall

from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.synthetic_injection._injection_enums import (
    InjectionFrequency,
    InjectionPosition,
)

logger = logging.getLogger(__name__)


class SyntheticToolCallInjector(MessagesTransformer, ABC):
    position: InjectionPosition
    frequency: InjectionFrequency
    call_id_prefix: str = "synthetic_"

    @abstractmethod
    async def get_tool_name(self) -> str: ...

    async def get_arguments(self) -> dict:
        return {}

    @abstractmethod
    async def get_content(self, messages: list[Message]) -> str | None:
        """Return the tool result content string, or None to skip injection."""
        ...

    def condition(self, messages: list[Message]) -> bool:
        """Override when frequency == CONDITIONAL."""
        return True

    async def transform(self, messages: list[Message]) -> list[Message]:
        tool_name = await self.get_tool_name()
        call_id: str

        # 1. Frequency gate
        match self.frequency:
            case InjectionFrequency.ONCE:
                call_id = f"synthetic_once_{tool_name}"
                if _has_tool_call_id(messages, call_id):
                    return messages
            case InjectionFrequency.REFRESH:
                call_id = f"synthetic_once_{tool_name}"
                messages = _remove_pair_by_call_id(messages, call_id)
            case InjectionFrequency.CONDITIONAL:
                if not self.condition(messages):
                    return messages
                call_id = f"{self.call_id_prefix}{uuid4().hex[:12]}"
            case InjectionFrequency.ALWAYS:
                call_id = f"{self.call_id_prefix}{uuid4().hex[:12]}"

        # 2. Content fetch
        content = await self.get_content(messages)
        if content is None:
            return messages

        # 3. Pair construction
        arguments = await self.get_arguments()
        pair = _build_pair(tool_name, call_id, arguments, content)

        # 4. Position splice
        match self.position:
            case InjectionPosition.AFTER_FIRST_USER:
                idx = next(
                    (i + 1 for i, m in enumerate(messages) if m.role == Role.USER),
                    len(messages),
                )
            case InjectionPosition.BEFORE_LAST_USER:
                idx = next(
                    (
                        i
                        for i in range(len(messages) - 1, -1, -1)
                        if messages[i].role == Role.USER
                    ),
                    len(messages),
                )
            case InjectionPosition.END:
                idx = len(messages)

        return messages[:idx] + list(pair) + messages[idx:]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_tool_call_id(messages: list[Message], call_id: str) -> bool:
    return any(
        m.role == Role.TOOL and m.tool_call_id == call_id for m in messages
    )


def _remove_pair_by_call_id(messages: list[Message], call_id: str) -> list[Message]:
    """Remove the ASSISTANT+TOOL pair that has the given call_id."""
    result: list[Message] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if (
            msg.role == Role.ASSISTANT
            and msg.tool_calls
            and any(tc.id == call_id for tc in msg.tool_calls)
        ):
            # Skip this ASSISTANT message and the following TOOL message(s) with this call_id
            i += 1
            while i < len(messages) and messages[i].role == Role.TOOL and messages[i].tool_call_id == call_id:
                i += 1
            continue
        result.append(msg)
        i += 1
    return result


def _build_pair(
    tool_name: str, call_id: str, arguments: dict, content: str
) -> tuple[Message, Message]:
    import json

    assistant_msg = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(
                id=call_id,
                type="function",
                function=FunctionCall(
                    name=tool_name,
                    arguments=json.dumps(arguments),
                ),
            )
        ],
    )
    tool_msg = Message(
        role=Role.TOOL,
        content=content,
        tool_call_id=call_id,
    )
    return assistant_msg, tool_msg
```

- [ ] **Step 4: Run tests**

```bash
source .venv/bin/activate && make test ARGS="-k test_synthetic_tool_call_injector -x"
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/quickapp/common/synthetic_injection/synthetic_tool_call_injector.py \
        src/tests/unit_tests/common/test_synthetic_tool_call_injector.py
git commit -m "feat: implement SyntheticToolCallInjector base class"
```

---

## Task 4 — `StagedToolSyntheticInjector` (TDD)

**Files:**
- Create: `src/quickapp/common/synthetic_injection/staged_tool_synthetic_injector.py`
- Create: `src/tests/unit_tests/common/test_staged_tool_synthetic_injector.py`

- [ ] **Step 1: Write failing tests**

Create `src/tests/unit_tests/common/test_staged_tool_synthetic_injector.py`:

```python
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from aidial_sdk.chat_completion import Message, Role

from quickapp.common.completion_result import CompletionResult
from quickapp.common.synthetic_injection._injection_enums import (
    InjectionFrequency,
    InjectionPosition,
)
from quickapp.common.synthetic_injection.staged_tool_synthetic_injector import (
    StagedToolSyntheticInjector,
)


def _make_staged_tool(sanitized_name: str, run_content: str = "tool result") -> MagicMock:
    """Build a minimal StagedBaseTool-like mock keyed by sanitized name."""
    tool_fn = SimpleNamespace(name=sanitized_name)
    tool_open_ai = SimpleNamespace(function=tool_fn)
    tool_config = SimpleNamespace(open_ai_tool=tool_open_ai)

    result = CompletionResult(content=run_content, content_type="text/plain")
    arun_mock = AsyncMock(return_value=result)

    tool = MagicMock()
    tool.tool_config = tool_config
    tool.arun = arun_mock
    return tool


class _ConcreteInjector(StagedToolSyntheticInjector):
    position = InjectionPosition.END
    frequency = InjectionFrequency.ALWAYS

    def __init__(self, tools, tool_name: str):
        super().__init__(tools)
        self._tool_name = tool_name

    async def get_tool_name(self) -> str:
        return self._tool_name


class TestStagedToolSyntheticInjector:

    @pytest.mark.asyncio
    async def test_calls_arun_and_returns_content(self):
        tool = _make_staged_tool("my_tool", "hello from tool")
        injector = _ConcreteInjector([tool], "my_tool")

        messages = [Message(role=Role.USER, content="hi")]
        result = await injector.transform(messages)

        assert len(result) == 3
        assert result[2].content == "hello from tool"
        tool.arun.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_when_tool_not_found(self):
        tool = _make_staged_tool("other_tool")
        injector = _ConcreteInjector([tool], "missing_tool")

        messages = [Message(role=Role.USER, content="hi")]
        result = await injector.transform(messages)

        assert result is messages
        tool.arun.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_passes_arguments_to_arun(self):
        tool = _make_staged_tool("arg_tool", "result")
        injector = _ConcreteInjector([tool], "arg_tool")
        # Override get_arguments for this test
        injector.get_arguments = AsyncMock(return_value={"key": "value"})

        messages = [Message(role=Role.USER, content="hi")]
        await injector.transform(messages)

        _, kwargs = tool.arun.call_args
        assert kwargs.get("key") == "value"

    @pytest.mark.asyncio
    async def test_multiple_tools_correct_one_selected(self):
        tool_a = _make_staged_tool("tool_a", "from a")
        tool_b = _make_staged_tool("tool_b", "from b")
        injector = _ConcreteInjector([tool_a, tool_b], "tool_b")

        messages = [Message(role=Role.USER, content="hi")]
        result = await injector.transform(messages)

        assert result[2].content == "from b"
        tool_a.arun.assert_not_awaited()
        tool_b.arun.assert_awaited_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && make test ARGS="-k test_staged_tool_synthetic_injector -x"
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `StagedToolSyntheticInjector`**

Create `src/quickapp/common/synthetic_injection/staged_tool_synthetic_injector.py`:

```python
import logging
from abc import ABC
from uuid import uuid4

from aidial_sdk.chat_completion import Message
from injector import inject

from quickapp.common.staged_base_tool import StagedBaseTool
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    SyntheticToolCallInjector,
)

logger = logging.getLogger(__name__)

_ARUN_SYNTHETIC_CALL_ID = "synthetic_injection_probe"


class StagedToolSyntheticInjector(SyntheticToolCallInjector, ABC):
    """Provides `get_content` by locating a `StagedBaseTool` by its sanitized
    OpenAI function name and calling `tool.arun()` with the declared arguments."""

    @inject
    def __init__(self, tools: list[StagedBaseTool]):
        self.__tools: dict[str, StagedBaseTool] = {
            tool.tool_config.open_ai_tool.function.name: tool for tool in tools
        }

    async def get_content(self, messages: list[Message]) -> str | None:
        tool_name = await self.get_tool_name()
        tool = self.__tools.get(tool_name)
        if tool is None:
            logger.warning(
                "StagedToolSyntheticInjector: tool '%s' not found in staged tools, skipping",
                tool_name,
            )
            return None
        arguments = await self.get_arguments()
        result = await tool.arun(_ARUN_SYNTHETIC_CALL_ID, **arguments)
        return result.content if result else None
```

- [ ] **Step 4: Run tests**

```bash
source .venv/bin/activate && make test ARGS="-k test_staged_tool_synthetic_injector -x"
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/quickapp/common/synthetic_injection/staged_tool_synthetic_injector.py \
        src/tests/unit_tests/common/test_staged_tool_synthetic_injector.py
git commit -m "feat: implement StagedToolSyntheticInjector"
```

---

## Task 5 — Migrate `_TimestampInjectionTransformer`

**Files:**
- Modify: `src/quickapp/timestamp_tooling/_timestamp_injection_transformer.py`
- Modify: `src/tests/unit_tests/timestamp_tooling/test_timestamp_injection_transformer.py`

**Note on call_id prefix:** `_timestamp_annotation_transformer.py` detects synthetic timestamp messages via `msg.tool_call_id.startswith(SYNTHETIC_TIMESTAMP_CALL_PREFIX)`. The migrated injector sets `call_id_prefix = SYNTHETIC_TIMESTAMP_CALL_PREFIX` so this detection continues to work unchanged.

- [ ] **Step 1: Rewrite `_TimestampInjectionTransformer`**

Full replacement for `src/quickapp/timestamp_tooling/_timestamp_injection_transformer.py`:

```python
from aidial_sdk.chat_completion import Message
from injector import ProviderOf, inject

from quickapp.common.synthetic_injection._injection_enums import (
    InjectionFrequency,
    InjectionPosition,
)
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    SyntheticToolCallInjector,
)
from quickapp.common.time_provider import TimeProvider
from quickapp.config.application import ApplicationConfig
from quickapp.timestamp_tooling._tool_configs import (
    CURRENT_TIMESTAMP_TOOL_NAME,
    SYNTHETIC_TIMESTAMP_CALL_PREFIX,
)


class _TimestampInjectionTransformer(SyntheticToolCallInjector):
    """Appends a synthetic tool-call + tool-result pair with the current
    timestamp at the end of the message list on every request turn."""

    position = InjectionPosition.END
    frequency = InjectionFrequency.ALWAYS
    call_id_prefix = SYNTHETIC_TIMESTAMP_CALL_PREFIX

    @inject
    def __init__(
        self,
        time_provider: TimeProvider,
        config_provider: ProviderOf[ApplicationConfig],
    ):
        self.__time_provider = time_provider
        self.__config_provider = config_provider

    async def get_tool_name(self) -> str:
        return CURRENT_TIMESTAMP_TOOL_NAME

    async def get_content(self, messages: list[Message]) -> str | None:
        features = self.__config_provider.get().features
        if features is None or features.timestamp is None or not messages:
            return None
        now = self.__time_provider.now()
        return self.__time_provider.format_timestamp(now)
```

- [ ] **Step 2: Update the tests**

The only change in `test_timestamp_injection_transformer.py` is:
1. Each test method becomes `async def` + `@pytest.mark.asyncio` (done in Task 2, Step 8 — already applied)
2. No further changes needed: `call_id.startswith(SYNTHETIC_TIMESTAMP_CALL_PREFIX)` still holds since `call_id_prefix = SYNTHETIC_TIMESTAMP_CALL_PREFIX` is set on the migrated class.

The test for `test_empty_messages_returns_empty` currently checks `assert result is messages`. After migration, `get_content` returns `None` when `not messages`, so `transform` returns `messages` unchanged — `result is messages` still holds. ✓

- [ ] **Step 3: Run tests**

```bash
source .venv/bin/activate && make test ARGS="-k test_timestamp_injection -x"
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/quickapp/timestamp_tooling/_timestamp_injection_transformer.py
git commit -m "refactor: migrate _TimestampInjectionTransformer to SyntheticToolCallInjector"
```

---

## Task 6 — Migrate `_InjectFileTransferInstructionTransformer`

**Files:**
- Modify: `src/quickapp/skills/_inject_file_transfer_instruction_transformer.py`
- Modify: `src/tests/unit_tests/skills_tests/test_inject_file_transfer_instruction_transformer.py`

**Note on call_id change:** `SYNTHETIC_TOOL_CALL_ID = "call_synthetic_file_transfer_0001"` is replaced by the deterministic base-class id `f"synthetic_once_{SKILL_READER_TOOL_NAME}"`. Existing history containing the old id will re-trigger injection on the next turn (one-time migration side-effect, accepted per design doc).

- [ ] **Step 1: Rewrite `_InjectFileTransferInstructionTransformer`**

Full replacement for `src/quickapp/skills/_inject_file_transfer_instruction_transformer.py`:

```python
import json
import logging

from aidial_sdk.chat_completion import Message
from injector import inject

from quickapp.common.synthetic_injection._injection_enums import (
    InjectionFrequency,
    InjectionPosition,
)
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    SyntheticToolCallInjector,
)
from quickapp.skills._tool_configs import SKILL_READER_TOOL_NAME
from quickapp.skills.agent_skills_provider import AgentSkillsProvider

logger = logging.getLogger(__name__)

BUILTIN_FILE_TRANSFER_SKILL = "tool-call-file-parameter-formatting"


class _InjectFileTransferInstructionTransformer(SyntheticToolCallInjector):
    """Injects a synthetic skill-reader tool call after the first USER message,
    exactly once per conversation."""

    position = InjectionPosition.AFTER_FIRST_USER
    frequency = InjectionFrequency.ONCE

    @inject
    def __init__(self, skills_provider: AgentSkillsProvider):
        self.__skills_provider = skills_provider

    async def get_tool_name(self) -> str:
        return SKILL_READER_TOOL_NAME

    async def get_arguments(self) -> dict:
        return {"skill_name": BUILTIN_FILE_TRANSFER_SKILL}

    async def get_content(self, messages: list[Message]) -> str | None:
        try:
            return self.__skills_provider.get_skill_content(BUILTIN_FILE_TRANSFER_SKILL)
        except (FileNotFoundError, ValueError) as e:
            logger.error("Builtin file transfer skill not found, skipping injection: %s", e)
            return None
```

- [ ] **Step 2: Update the tests**

In `test_inject_file_transfer_instruction_transformer.py`:

1. Remove the `SYNTHETIC_TOOL_CALL_ID` import and usage — replace with the new deterministic id.
2. Update `_assert_synthetic_pair` to use `f"synthetic_once_{SKILL_READER_TOOL_NAME}"` as the expected call_id.

Key changes:
```python
# Remove this import:
# from quickapp.skills._inject_file_transfer_instruction_transformer import (
#     BUILTIN_FILE_TRANSFER_SKILL,
#     SYNTHETIC_TOOL_CALL_ID,
#     ...
# )

# New expected call_id:
EXPECTED_CALL_ID = f"synthetic_once_{SKILL_READER_TOOL_NAME}"

def _assert_synthetic_pair(messages: list[Message], assistant_idx: int) -> None:
    assistant = messages[assistant_idx]
    tool = messages[assistant_idx + 1]

    assert assistant.role == Role.ASSISTANT
    assert assistant.tool_calls is not None
    assert len(assistant.tool_calls) == 1
    assert assistant.tool_calls[0].id == EXPECTED_CALL_ID
    assert assistant.tool_calls[0].function.name == SKILL_READER_TOOL_NAME
    assert BUILTIN_FILE_TRANSFER_SKILL in assistant.tool_calls[0].function.arguments

    assert tool.role == Role.TOOL
    assert tool.tool_call_id == EXPECTED_CALL_ID
    assert tool.content is not None
    assert tool.content
```

All test methods should already be `async def` + `@pytest.mark.asyncio` (done in Task 2, Step 9).

- [ ] **Step 3: Run tests**

```bash
source .venv/bin/activate && make test ARGS="-k test_inject_file_transfer -x"
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/quickapp/skills/_inject_file_transfer_instruction_transformer.py \
        src/tests/unit_tests/skills_tests/test_inject_file_transfer_instruction_transformer.py
git commit -m "refactor: migrate _InjectFileTransferInstructionTransformer to SyntheticToolCallInjector"
```

---

## Task 7 — Migrate `_AttachmentNotificationInjector`

**Files:**
- Modify: `src/quickapp/attachment_processing/_attachment_notification_injector.py`
- Modify: `src/tests/unit_tests/attachment_processing_tests/test_attachment_notification_injector.py`

- [ ] **Step 1: Rewrite `_AttachmentNotificationInjector`**

Full replacement for `src/quickapp/attachment_processing/_attachment_notification_injector.py`:

```python
import json
import logging

from aidial_sdk.chat_completion import Message
from injector import ProviderOf, inject

from quickapp.attachment_processing._context_entries import (
    AvailableContextToolResponse,
    build_context_entries,
    extract_seen_entries_from_messages,
    should_activate_context_tool,
)
from quickapp.attachment_processing._tool_configs import AVAILABLE_CONTEXT_TOOL_NAME
from quickapp.common.synthetic_injection._injection_enums import (
    InjectionFrequency,
    InjectionPosition,
)
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    SyntheticToolCallInjector,
)
from quickapp.config.application import ApplicationConfig
from quickapp.config.context import Context

logger = logging.getLogger(__name__)


class _AttachmentNotificationInjector(SyntheticToolCallInjector):
    """Injects synthetic tool call/result messages to inform the agent about
    available contexts when changes are detected."""

    position = InjectionPosition.END
    frequency = InjectionFrequency.CONDITIONAL

    @inject
    def __init__(self, config_provider: ProviderOf[ApplicationConfig]):
        self.__config_provider: ProviderOf[ApplicationConfig] = config_provider

    async def get_tool_name(self) -> str:
        return AVAILABLE_CONTEXT_TOOL_NAME

    def condition(self, messages: list[Message]) -> bool:
        contexts = list(self.__config_provider.get().contexts)
        return should_activate_context_tool(contexts, messages)

    async def get_content(self, messages: list[Message]) -> str | None:
        contexts = list(self.__config_provider.get().contexts)
        seen_entries = extract_seen_entries_from_messages(messages)
        current_urls, entries = build_context_entries(contexts, seen_entries)

        if current_urls == set(seen_entries) and not any(e.status for e in entries):
            return None

        tool_response = AvailableContextToolResponse(entries=entries)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Injecting synthetic context notification with %d entries",
                len(entries),
            )

        return json.dumps(tool_response.model_dump(exclude_none=True), ensure_ascii=False)
```

- [ ] **Step 2: Verify tests (already async from Task 2, Step 10)**

All test methods are already `async def` + `@pytest.mark.asyncio`. No assertion changes needed — the injector still uses `InjectionFrequency.CONDITIONAL` which generates random call_ids, matching the old behaviour.

- [ ] **Step 3: Run tests**

```bash
source .venv/bin/activate && make test ARGS="-k test_attachment_notification -x"
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/quickapp/attachment_processing/_attachment_notification_injector.py
git commit -m "refactor: migrate _AttachmentNotificationInjector to SyntheticToolCallInjector"
```

---

## Task 8 — Format, lint, full test run

**Files:** none (validation only)

- [ ] **Step 1: Format**

```bash
source .venv/bin/activate && make format
```

Expected: no diff (code already formatted). If schema changed, `docs/generated-app-schema.json` is updated.

- [ ] **Step 2: Lint**

```bash
source .venv/bin/activate && make lint
```

Expected: all checks pass (mypy, flake8, black, isort, autoflake, schema check).

Fix any mypy errors before proceeding. Common issues:
- Missing `-> None` return type on `setup()`
- Abstract class attributes (`position`, `frequency`) not recognized by mypy — add `ClassVar` if needed

- [ ] **Step 3: Full test run**

```bash
source .venv/bin/activate && make test
```

Expected: all tests pass.

- [ ] **Step 4: Final commit (if any formatting changes)**

```bash
git add docs/generated-app-schema.json  # only if schema changed
git commit -m "chore: post-migration format and lint fixes"
```
