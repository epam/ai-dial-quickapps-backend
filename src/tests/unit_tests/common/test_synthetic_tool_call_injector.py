from unittest.mock import patch

import pytest
from aidial_sdk.chat_completion import Message, Role

from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    SyntheticToolCallInjector,
)
from quickapp.common.tool_call_result import ToolCallResult
from tests.unit_tests.common.common import make_provider

_TIME_MODULE = "quickapp.common.synthetic_injection.synthetic_tool_call_injector.time"
_EPOCH_HOURS_NOW = 500_000

# ---------------------------------------------------------------------------
# Minimal concrete implementations for testing
# ---------------------------------------------------------------------------


class _AlwaysInjector(SyntheticToolCallInjector):
    async def get_tool_name(self) -> str:
        return "test_tool"

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return InjectionFrequency.ALWAYS

    async def get_content(self, messages: list[Message]) -> str | None:
        return "test content"


class _AppendIfChangedInjector(SyntheticToolCallInjector):
    def __init__(
        self,
        content: str = "append content",
        enrichers: list[ToolCallResultEnricher] | None = None,
    ):
        super().__init__(make_provider(enrichers) if enrichers else None)
        self._content = content

    async def get_tool_name(self) -> str:
        return "append_tool"

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return InjectionFrequency.APPEND_IF_CHANGED

    async def get_content(self, messages: list[Message]) -> str | None:
        return self._content


class _ParamDrivenInjector(SyntheticToolCallInjector):
    def __init__(
        self,
        arguments: dict,
        frequency: InjectionFrequency,
        content: str | None = None,
    ):
        super().__init__()
        self._arguments = arguments
        self._frequency = frequency
        self._content = content

    async def get_tool_name(self) -> str:
        return "param_tool"

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return self._frequency

    async def get_arguments(self) -> dict:
        return self._arguments

    async def get_content(self, messages: list[Message]) -> str | None:
        return self._content or f"content for {self._arguments}"


class _ConditionalInjector(SyntheticToolCallInjector):
    def __init__(self, condition_result: bool = True):
        super().__init__()
        self._condition_result = condition_result

    async def get_tool_name(self) -> str:
        return "cond_tool"

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return InjectionFrequency.ALWAYS

    async def get_content(self, messages: list[Message]) -> str | None:
        return "cond content" if self._condition_result else None


class _NullContentInjector(SyntheticToolCallInjector):
    async def get_tool_name(self) -> str:
        return "null_tool"

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return InjectionFrequency.ALWAYS

    async def get_content(self, messages: list[Message]) -> str | None:
        return None


class _ShouldNotInjectInjector(SyntheticToolCallInjector):
    async def get_tool_name(self) -> str:
        return "gate_tool"

    async def should_inject(self, messages: list[Message]) -> bool:
        return False

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return InjectionFrequency.ALWAYS

    async def get_content(self, messages: list[Message]) -> str | None:
        return "should not appear"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user(content: str = "hi") -> Message:
    return Message(role=Role.USER, content=content)


def _assert_synthetic_pair(
    messages: list[Message], assistant_idx: int, tool_name: str, content: str
) -> str:
    """Assert messages[assistant_idx:assistant_idx+2] is a valid synthetic pair.
    Returns the call_id."""
    assistant = messages[assistant_idx]
    tool = messages[assistant_idx + 1]

    assert assistant.role == Role.ASSISTANT
    assert assistant.tool_calls is not None
    assert len(assistant.tool_calls) == 1
    assert assistant.tool_calls[0].function.name == tool_name
    call_id = assistant.tool_calls[0].id
    assert call_id, f"call_id should be non-empty, got {call_id!r}"

    assert tool.role == Role.TOOL
    assert tool.tool_call_id == call_id
    assert tool.content == content

    return call_id


# ---------------------------------------------------------------------------
# Tests: ALWAYS → END
# ---------------------------------------------------------------------------


class TestAlways:
    @pytest.mark.asyncio
    async def test_appends_pair_at_end(self):
        injector = _AlwaysInjector()
        messages = [_user("hello")]

        result = await injector.transform(messages)

        assert len(result) == 3
        assert result[0] is messages[0]
        _assert_synthetic_pair(result, 1, "test_tool", "test content")

    @pytest.mark.asyncio
    async def test_accumulates_on_multiple_calls(self):
        injector = _AlwaysInjector()
        messages = [_user("hello")]

        result = await injector.transform(messages)
        result = await injector.transform(result)

        assert len(result) == 5  # 1 user + 2 pairs

    @pytest.mark.asyncio
    async def test_empty_messages_appends_pair(self):
        injector = _AlwaysInjector()
        result = await injector.transform([])
        assert len(result) == 2
        _assert_synthetic_pair(result, 0, "test_tool", "test content")

    @pytest.mark.asyncio
    async def test_uses_random_call_id(self):
        injector = _AlwaysInjector()
        result1 = await injector.transform([_user("hi")])
        result2 = await injector.transform([_user("hi")])

        id1 = _assert_synthetic_pair(result1, 1, "test_tool", "test content")
        id2 = _assert_synthetic_pair(result2, 1, "test_tool", "test content")
        assert id1 != id2


# ---------------------------------------------------------------------------
# Tests: APPEND_IF_CHANGED
# ---------------------------------------------------------------------------


class TestAppendIfChanged:
    @pytest.mark.asyncio
    async def test_injects_after_first_user_on_first_call(self):
        injector = _AppendIfChangedInjector()
        messages = [_user("first"), Message(role=Role.ASSISTANT, content="reply"), _user("second")]

        result = await injector.transform(messages)

        # Injected after first user message
        assert len(result) == 5
        assert result[0].role == Role.USER
        _assert_synthetic_pair(result, 1, "append_tool", "append content")
        assert result[3].role == Role.ASSISTANT
        assert result[4].role == Role.USER

    @pytest.mark.asyncio
    async def test_skips_when_content_unchanged(self):
        injector = _AppendIfChangedInjector()
        result = await injector.transform([_user("hello")])
        assert len(result) == 3

        result2 = await injector.transform(result)
        assert len(result2) == 3  # unchanged

    @pytest.mark.asyncio
    async def test_appends_at_end_when_content_changed(self):
        injector = _AppendIfChangedInjector(content="v1")
        result = await injector.transform([_user("hello")])
        assert len(result) == 3

        injector._content = "v2"
        result = await injector.transform(result)

        # v1 preserved, v2 appended at end
        assert len(result) == 5
        _assert_synthetic_pair(result, 1, "append_tool", "v1")
        _assert_synthetic_pair(result, 3, "append_tool", "v2")

    @pytest.mark.asyncio
    async def test_uses_deterministic_call_id(self):
        injector = _AppendIfChangedInjector()
        id1 = _assert_synthetic_pair(
            await injector.transform([_user("hi")]), 1, "append_tool", "append content"
        )
        id2 = _assert_synthetic_pair(
            await injector.transform([_user("hi")]), 1, "append_tool", "append content"
        )
        assert id1 == id2
        assert id1.startswith("synth_append_tool_")

    @pytest.mark.asyncio
    async def test_no_user_message_appends_at_end(self):
        injector = _AppendIfChangedInjector()
        result = await injector.transform([Message(role=Role.SYSTEM, content="sys")])
        assert result[0].role == Role.SYSTEM
        _assert_synthetic_pair(result, 1, "append_tool", "append content")


# ---------------------------------------------------------------------------
# Tests: APPEND_IF_CHANGED with different arguments
# ---------------------------------------------------------------------------


class TestAppendIfChangedDifferentArgs:
    @pytest.mark.asyncio
    async def test_both_injected_when_args_differ(self):
        injector_a = _ParamDrivenInjector({"key": "a"}, InjectionFrequency.APPEND_IF_CHANGED)
        injector_b = _ParamDrivenInjector({"key": "b"}, InjectionFrequency.APPEND_IF_CHANGED)
        result = await injector_a.transform([_user("hello")])
        result = await injector_b.transform(result)

        assert len(result) == 5
        # injector_b runs second and inserts at AFTER_FIRST_USER, pushing injector_a's pair to [3]
        id_b = _assert_synthetic_pair(result, 1, "param_tool", "content for {'key': 'b'}")
        id_a = _assert_synthetic_pair(result, 3, "param_tool", "content for {'key': 'a'}")
        assert id_a != id_b

    @pytest.mark.asyncio
    async def test_deduplicated_when_args_and_content_same(self):
        injector_a = _ParamDrivenInjector({"key": "same"}, InjectionFrequency.APPEND_IF_CHANGED)
        injector_b = _ParamDrivenInjector({"key": "same"}, InjectionFrequency.APPEND_IF_CHANGED)
        result = await injector_a.transform([_user("hello")])
        result = await injector_b.transform(result)

        assert len(result) == 3  # second injector skips


# ---------------------------------------------------------------------------
# Tests: should_inject gate
# ---------------------------------------------------------------------------


class TestShouldInjectGate:
    @pytest.mark.asyncio
    async def test_skips_injection_when_should_inject_false(self):
        injector = _ShouldNotInjectInjector()
        messages = [_user("hello")]

        result = await injector.transform(messages)

        assert result is messages

    @pytest.mark.asyncio
    async def test_injects_when_should_inject_true_by_default(self):
        injector = _AlwaysInjector()
        result = await injector.transform([_user("hello")])
        assert len(result) == 3


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

    @pytest.mark.asyncio
    async def test_skips_when_condition_false(self):
        injector = _ConditionalInjector(condition_result=False)
        messages = [_user("hello")]

        result = await injector.transform(messages)

        assert result is messages


# ---------------------------------------------------------------------------
# Tests: enrichment
# ---------------------------------------------------------------------------


class _StampingEnricher(ToolCallResultEnricher):
    def __init__(self, marker: str = "x"):
        self._marker = marker

    def enrich(self, result: ToolCallResult) -> None:
        if result.state is None:
            result.state = {}
        result.state["marker"] = self._marker


class TestEnrichment:
    @pytest.mark.asyncio
    async def test_enriched_state_lands_on_synthetic_tool_message(self):
        injector = _AppendIfChangedInjector(enrichers=[_StampingEnricher("seen")])
        result = await injector.transform([_user("hi")])

        tool_msg = result[2]
        assert tool_msg.custom_content is not None
        assert tool_msg.custom_content.state == {"marker": "seen"}

    @pytest.mark.asyncio
    async def test_no_custom_content_when_no_enrichers(self):
        injector = _AppendIfChangedInjector()
        result = await injector.transform([_user("hi")])

        tool_msg = result[2]
        assert tool_msg.custom_content is None

    @pytest.mark.asyncio
    async def test_multiple_enrichers_compose(self):
        class _SecondEnricher(ToolCallResultEnricher):
            def enrich(self, result: ToolCallResult) -> None:
                if result.state is None:
                    result.state = {}
                result.state["extra"] = "yes"

        injector = _AppendIfChangedInjector(
            enrichers=[_StampingEnricher("first"), _SecondEnricher()],
        )
        result = await injector.transform([_user("hi")])

        tool_msg = result[2]
        assert tool_msg.custom_content is not None
        assert tool_msg.custom_content.state == {"marker": "first", "extra": "yes"}

    @pytest.mark.asyncio
    async def test_assistant_message_has_no_custom_content(self):
        injector = _AppendIfChangedInjector(enrichers=[_StampingEnricher()])
        result = await injector.transform([_user("hi")])

        assistant_msg = result[1]
        assert assistant_msg.custom_content is None


# ---------------------------------------------------------------------------
# Tests: custom call_id_prefix
# ---------------------------------------------------------------------------


class TestCustomCallIdPrefix:
    @pytest.mark.asyncio
    async def test_custom_prefix_applied(self):
        class _PrefixedInjector(SyntheticToolCallInjector):
            call_id_prefix = "my_prefix_"

            async def get_tool_name(self) -> str:
                return "prefixed_tool"

            async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
                return InjectionFrequency.ALWAYS

            async def get_content(self, messages: list[Message]) -> str | None:
                return "content"

        injector = _PrefixedInjector()
        result = await injector.transform([_user("hi")])
        call_id = _assert_synthetic_pair(result, 1, "prefixed_tool", "content")
        assert call_id.startswith("my_prefix_")


# ---------------------------------------------------------------------------
# Tests: DAILY_REFRESH
# ---------------------------------------------------------------------------


class _DailyRefreshInjector(SyntheticToolCallInjector):
    def __init__(self, content: str = "daily content"):
        super().__init__()
        self._content = content

    async def get_tool_name(self) -> str:
        return "daily_tool"

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return InjectionFrequency.DAILY_REFRESH

    async def get_content(self, messages: list[Message]) -> str | None:
        return self._content


class TestDailyRefresh:
    @pytest.mark.asyncio
    async def test_first_injection_placed_after_first_user_message(self):
        injector = _DailyRefreshInjector()
        messages = [_user("first"), Message(role=Role.ASSISTANT, content="reply"), _user("second")]

        with patch(_TIME_MODULE) as mock_time:
            mock_time.time.return_value = _EPOCH_HOURS_NOW * 3600
            result = await injector.transform(messages)

        assert len(result) == 5
        assert result[0].role == Role.USER
        _assert_synthetic_pair(result, 1, "daily_tool", "daily content")
        assert result[3].role == Role.ASSISTANT
        assert result[4].role == Role.USER

    @pytest.mark.asyncio
    async def test_skips_when_pair_is_fresh(self):
        injector = _DailyRefreshInjector()
        messages = [_user("hi")]

        with patch(_TIME_MODULE) as mock_time:
            mock_time.time.return_value = _EPOCH_HOURS_NOW * 3600
            result = await injector.transform(messages)

        assert len(result) == 3

        with patch(_TIME_MODULE) as mock_time:
            mock_time.time.return_value = (_EPOCH_HOURS_NOW + 1) * 3600
            result2 = await injector.transform(result)

        assert len(result2) == 3  # no new injection

    @pytest.mark.asyncio
    async def test_restamps_in_place_when_stale_and_content_unchanged(self):
        injector = _DailyRefreshInjector(content="same content")
        messages = [_user("hi")]

        with patch(_TIME_MODULE) as mock_time:
            mock_time.time.return_value = _EPOCH_HOURS_NOW * 3600
            result = await injector.transform(messages)

        assert len(result) == 3
        old_call_id = _assert_synthetic_pair(result, 1, "daily_tool", "same content")

        with patch(_TIME_MODULE) as mock_time:
            mock_time.time.return_value = (_EPOCH_HOURS_NOW + 25) * 3600
            result2 = await injector.transform(result)

        assert len(result2) == 3  # still 3 — replaced in place, not appended
        new_call_id = _assert_synthetic_pair(result2, 1, "daily_tool", "same content")
        assert new_call_id != old_call_id  # timestamp refreshed

    @pytest.mark.asyncio
    async def test_appends_at_end_when_stale_and_content_changed(self):
        injector = _DailyRefreshInjector(content="v1")
        messages = [_user("hi")]

        with patch(_TIME_MODULE) as mock_time:
            mock_time.time.return_value = _EPOCH_HOURS_NOW * 3600
            result = await injector.transform(messages)

        assert len(result) == 3
        _assert_synthetic_pair(result, 1, "daily_tool", "v1")

        injector._content = "v2"
        with patch(_TIME_MODULE) as mock_time:
            mock_time.time.return_value = (_EPOCH_HOURS_NOW + 25) * 3600
            result2 = await injector.transform(result)

        assert len(result2) == 5  # old pair preserved + new pair appended
        _assert_synthetic_pair(result2, 1, "daily_tool", "v1")
        _assert_synthetic_pair(result2, 3, "daily_tool", "v2")

    @pytest.mark.asyncio
    async def test_skips_when_content_is_none(self):
        class _NullDailyInjector(SyntheticToolCallInjector):
            async def get_tool_name(self) -> str:
                return "null_daily"

            async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
                return InjectionFrequency.DAILY_REFRESH

            async def get_content(self, messages: list[Message]) -> str | None:
                return None

        injector = _NullDailyInjector()
        messages = [_user("hi")]

        with patch(_TIME_MODULE) as mock_time:
            mock_time.time.return_value = _EPOCH_HOURS_NOW * 3600
            result = await injector.transform(messages)

        assert result is messages

    @pytest.mark.asyncio
    async def test_uses_deterministic_call_id_for_same_content(self):
        injector = _DailyRefreshInjector()
        messages = [_user("hi")]

        with patch(_TIME_MODULE) as mock_time:
            mock_time.time.return_value = _EPOCH_HOURS_NOW * 3600
            id1 = _assert_synthetic_pair(
                await injector.transform(messages), 1, "daily_tool", "daily content"
            )
            id2 = _assert_synthetic_pair(
                await injector.transform(messages), 1, "daily_tool", "daily content"
            )

        assert id1 == id2
        assert "dr" in id1
