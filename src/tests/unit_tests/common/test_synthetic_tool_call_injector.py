import pytest
from aidial_sdk.chat_completion import Message, Role

from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    SyntheticToolCallInjector,
)
from quickapp.common.tool_call_result import ToolCallResult
from tests.unit_tests.common.common import make_provider

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
# Tests: ALWAYS → before last USER
# ---------------------------------------------------------------------------


class TestAlways:
    @pytest.mark.asyncio
    async def test_injects_pair_before_last_user(self):
        injector = _AlwaysInjector()
        messages = [_user("hello")]

        result = await injector.transform(messages)

        assert len(result) == 3
        _assert_synthetic_pair(result, 0, "test_tool", "test content")
        assert result[2] is messages[0]

    @pytest.mark.asyncio
    async def test_accumulates_on_multiple_calls(self):
        injector = _AlwaysInjector()
        messages = [_user("hello")]

        result = await injector.transform(messages)
        result = await injector.transform(result)

        assert len(result) == 5  # 2 pairs + 1 user
        assert result[4].role == Role.USER

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

        id1 = _assert_synthetic_pair(result1, 0, "test_tool", "test content")
        id2 = _assert_synthetic_pair(result2, 0, "test_tool", "test content")
        assert id1 != id2


# ---------------------------------------------------------------------------
# Tests: APPEND_IF_CHANGED
# ---------------------------------------------------------------------------


class TestAppendIfChanged:
    @pytest.mark.asyncio
    async def test_injects_before_last_user_on_first_call(self):
        injector = _AppendIfChangedInjector()
        messages = [_user("first"), Message(role=Role.ASSISTANT, content="reply"), _user("second")]

        result = await injector.transform(messages)

        assert len(result) == 5
        assert result[0].role == Role.USER
        assert result[0].content == "first"
        assert result[1].role == Role.ASSISTANT
        assert result[1].content == "reply"
        _assert_synthetic_pair(result, 2, "append_tool", "append content")
        assert result[4].role == Role.USER
        assert result[4].content == "second"

    @pytest.mark.asyncio
    async def test_skips_when_content_unchanged(self):
        injector = _AppendIfChangedInjector()
        result = await injector.transform([_user("hello")])
        assert len(result) == 3

        result2 = await injector.transform(result)
        assert len(result2) == 3  # unchanged

    @pytest.mark.asyncio
    async def test_injects_before_last_user_when_content_changed(self):
        injector = _AppendIfChangedInjector(content="v1")
        result = await injector.transform([_user("hello")])
        assert len(result) == 3

        injector._content = "v2"
        result = await injector.transform(result)

        # v1 preserved, v2 injected before last USER
        assert len(result) == 5
        _assert_synthetic_pair(result, 0, "append_tool", "v1")
        _assert_synthetic_pair(result, 2, "append_tool", "v2")
        assert result[4].role == Role.USER

    @pytest.mark.asyncio
    async def test_uses_deterministic_call_id(self):
        injector = _AppendIfChangedInjector()
        id1 = _assert_synthetic_pair(
            await injector.transform([_user("hi")]), 0, "append_tool", "append content"
        )
        id2 = _assert_synthetic_pair(
            await injector.transform([_user("hi")]), 0, "append_tool", "append content"
        )
        assert id1 == id2
        assert id1.startswith("synth_t_")

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
        # injector_b runs second and inserts before last USER, after injector_a's pair
        id_a = _assert_synthetic_pair(result, 0, "param_tool", "content for {'key': 'a'}")
        id_b = _assert_synthetic_pair(result, 2, "param_tool", "content for {'key': 'b'}")
        assert id_a != id_b
        assert result[4].role == Role.USER

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

        tool_msg = result[1]
        assert tool_msg.custom_content is not None
        assert tool_msg.custom_content.state == {"marker": "seen"}

    @pytest.mark.asyncio
    async def test_no_custom_content_when_no_enrichers(self):
        injector = _AppendIfChangedInjector()
        result = await injector.transform([_user("hi")])

        tool_msg = result[1]
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

        tool_msg = result[1]
        assert tool_msg.custom_content is not None
        assert tool_msg.custom_content.state == {"marker": "first", "extra": "yes"}

    @pytest.mark.asyncio
    async def test_assistant_message_has_no_custom_content(self):
        injector = _AppendIfChangedInjector(enrichers=[_StampingEnricher()])
        result = await injector.transform([_user("hi")])

        assistant_msg = result[0]
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
        call_id = _assert_synthetic_pair(result, 0, "prefixed_tool", "content")
        assert call_id.startswith("my_prefix_")


# ---------------------------------------------------------------------------
# Tests: replace-in-place (same args+content, different call_id — e.g. TTL re-stamp)
# ---------------------------------------------------------------------------


class _TTLStampingInjector(SyntheticToolCallInjector):
    """Injector that embeds an explicit TTL expiry in the call_id for testing."""

    def __init__(self, content: str = "ttl content", ttl_expiry_seconds: int | None = None):
        super().__init__()
        self._content = content
        self._ttl_expiry_seconds = ttl_expiry_seconds

    async def get_tool_name(self) -> str:
        return "timed_tool"

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return InjectionFrequency.APPEND_IF_CHANGED

    async def get_content(self, messages: list[Message]) -> str | None:
        return self._content

    def make_call_id(
        self, tool_name: str, arguments: dict, content: str, ttl_expiry_seconds: int | None = None
    ) -> str:
        return super().make_call_id(tool_name, arguments, content, self._ttl_expiry_seconds)


class TestReplaceInPlace:
    @pytest.mark.asyncio
    async def test_replace_in_place_when_content_same_but_call_id_differs(self):
        injector = _TTLStampingInjector(content="same", ttl_expiry_seconds=1000)
        messages = [_user("hi")]

        result = await injector.transform(messages)
        assert len(result) == 3
        old_call_id = _assert_synthetic_pair(result, 0, "timed_tool", "same")
        assert "_ttl_" in old_call_id

        injector._ttl_expiry_seconds = 2000  # different expiry → different call_id
        result2 = await injector.transform(result)

        assert len(result2) == 3  # replaced in place, not appended
        new_call_id = _assert_synthetic_pair(result2, 0, "timed_tool", "same")
        assert new_call_id != old_call_id  # call_id updated with new expiry

    @pytest.mark.asyncio
    async def test_appends_when_content_changes_regardless_of_ttl(self):
        injector = _TTLStampingInjector(content="v1", ttl_expiry_seconds=1000)
        messages = [_user("hi")]

        result = await injector.transform(messages)
        assert len(result) == 3

        injector._content = "v2"
        injector._ttl_expiry_seconds = 2000
        result2 = await injector.transform(result)

        assert len(result2) == 5  # old pair kept, new before last USER
        _assert_synthetic_pair(result2, 0, "timed_tool", "v1")
        _assert_synthetic_pair(result2, 2, "timed_tool", "v2")
        assert result2[4].role == Role.USER

    @pytest.mark.asyncio
    async def test_call_id_contains_ttl_marker_when_expiry_set(self):
        injector = _TTLStampingInjector(content="data", ttl_expiry_seconds=9999)
        result = await injector.transform([_user("hi")])
        call_id = _assert_synthetic_pair(result, 0, "timed_tool", "data")
        assert "_ttl_" in call_id

    @pytest.mark.asyncio
    async def test_call_id_has_no_ttl_marker_when_expiry_not_set(self):
        injector = _TTLStampingInjector(content="data", ttl_expiry_seconds=None)
        result = await injector.transform([_user("hi")])
        call_id = _assert_synthetic_pair(result, 0, "timed_tool", "data")
        assert "_ttl_" not in call_id
