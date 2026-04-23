import pytest
from aidial_sdk.chat_completion import Message, Role

from quickapp.common.synthetic_injection.injection_enums import (
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


class _ParamDrivenOnceInjector(SyntheticToolCallInjector):
    position = InjectionPosition.END
    frequency = InjectionFrequency.ONCE

    def __init__(self, arguments: dict):
        self._arguments = arguments

    async def get_tool_name(self) -> str:
        return "param_tool"

    async def get_arguments(self) -> dict:
        return self._arguments

    async def get_content(self, messages: list[Message]) -> str | None:
        return f"content for {self._arguments}"


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
    assert call_id, f"call_id should be non-empty, got {call_id!r}"

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
        assert result1[1].tool_calls is not None
        assert result2[1].tool_calls is not None
        id1 = result1[1].tool_calls[0].id
        id2 = result2[1].tool_calls[0].id
        assert id1 == id2
        assert id1.startswith("synth_once_once_tool_")

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
        # Old pair removed, new pair inserted — still 3 total (not 5)
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

        assert result1[1].tool_calls is not None
        assert result2[1].tool_calls is not None
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
        assert result[1].tool_calls is not None
        call_id = result[1].tool_calls[0].id
        assert call_id.startswith("my_prefix_")


# ---------------------------------------------------------------------------
# Tests: ONCE with different arguments
# ---------------------------------------------------------------------------


class TestOnceDifferentArguments:
    @pytest.mark.asyncio
    async def test_both_injected_when_args_differ(self):
        injector_a = _ParamDrivenOnceInjector({"key": "a"})
        injector_b = _ParamDrivenOnceInjector({"key": "b"})
        messages = [_user("hello")]

        result = await injector_a.transform(messages)
        result = await injector_b.transform(result)

        # Both pairs injected: 1 user + 2 × (assistant + tool) = 5
        assert len(result) == 5
        assert result[1].tool_calls is not None
        assert result[3].tool_calls is not None
        call_id_a = result[1].tool_calls[0].id
        call_id_b = result[3].tool_calls[0].id
        assert call_id_a != call_id_b

    @pytest.mark.asyncio
    async def test_deduplicated_when_args_same(self):
        injector_a = _ParamDrivenOnceInjector({"key": "same"})
        injector_b = _ParamDrivenOnceInjector({"key": "same"})
        messages = [_user("hello")]

        result = await injector_a.transform(messages)
        result = await injector_b.transform(result)

        # Second injector sees the existing call_id and skips — only one pair
        assert len(result) == 3
