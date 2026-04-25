import pytest
from aidial_sdk.chat_completion import Message, Role

from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    SyntheticToolCallInjector,
)

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
    def __init__(self, content: str = "append content"):
        self._content = content

    async def get_tool_name(self) -> str:
        return "append_tool"

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return InjectionFrequency.APPEND_IF_CHANGED

    async def get_content(self, messages: list[Message]) -> str | None:
        return self._content


class _RefreshIfChangedInjector(SyntheticToolCallInjector):
    def __init__(self, content: str = "refresh content"):
        self._content = content

    async def get_tool_name(self) -> str:
        return "refresh_tool"

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return InjectionFrequency.REFRESH_IF_CHANGED

    async def get_content(self, messages: list[Message]) -> str | None:
        return self._content


class _ParamDrivenInjector(SyntheticToolCallInjector):
    def __init__(
        self,
        arguments: dict,
        frequency: InjectionFrequency,
        content: str | None = None,
    ):
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
# Tests: REFRESH_IF_CHANGED
# ---------------------------------------------------------------------------


class TestRefreshIfChanged:
    @pytest.mark.asyncio
    async def test_injects_after_first_user_on_first_call(self):
        injector = _RefreshIfChangedInjector()
        messages = [_user("hello")]

        result = await injector.transform(messages)

        assert len(result) == 3
        assert result[0].role == Role.USER
        _assert_synthetic_pair(result, 1, "refresh_tool", "refresh content")

    @pytest.mark.asyncio
    async def test_skips_when_content_unchanged(self):
        injector = _RefreshIfChangedInjector()
        result = await injector.transform([_user("hello")])
        assert len(result) == 3

        result2 = await injector.transform(result)
        assert len(result2) == 3  # unchanged

    @pytest.mark.asyncio
    async def test_replaces_when_content_changed(self):
        injector = _RefreshIfChangedInjector(content="v1")
        result = await injector.transform([_user("hello")])
        assert len(result) == 3

        injector._content = "v2"
        result = await injector.transform(result)

        assert len(result) == 3  # replaced, not accumulated
        _assert_synthetic_pair(result, 1, "refresh_tool", "v2")

    @pytest.mark.asyncio
    async def test_no_user_message_appends_at_end(self):
        injector = _RefreshIfChangedInjector()
        result = await injector.transform([Message(role=Role.SYSTEM, content="sys")])
        assert result[0].role == Role.SYSTEM
        _assert_synthetic_pair(result, 1, "refresh_tool", "refresh content")


# ---------------------------------------------------------------------------
# Tests: REFRESH_IF_CHANGED scoped to same tool+args
# ---------------------------------------------------------------------------


class TestRefreshIfChangedArgScoping:
    @pytest.mark.asyncio
    async def test_appends_when_args_differ(self):
        """Different args = different scope; existing pair must not be removed."""
        injector_a = _ParamDrivenInjector({"k": "a"}, InjectionFrequency.REFRESH_IF_CHANGED)
        injector_b = _ParamDrivenInjector({"k": "b"}, InjectionFrequency.REFRESH_IF_CHANGED)
        messages = [_user("hello")]

        result = await injector_a.transform(messages)
        result = await injector_b.transform(result)

        assert len(result) == 5  # both pairs present

    @pytest.mark.asyncio
    async def test_replaces_only_matching_args_pair(self):
        """Content change for args={k:a} must not remove the pair for args={k:b}."""
        injector_a_v1 = _ParamDrivenInjector(
            {"k": "a"}, InjectionFrequency.REFRESH_IF_CHANGED, content="a-v1"
        )
        injector_b = _ParamDrivenInjector(
            {"k": "b"}, InjectionFrequency.REFRESH_IF_CHANGED, content="b-v1"
        )
        result = await injector_a_v1.transform([_user("hello")])
        result = await injector_b.transform(result)
        assert len(result) == 5

        injector_a_v2 = _ParamDrivenInjector(
            {"k": "a"}, InjectionFrequency.REFRESH_IF_CHANGED, content="a-v2"
        )
        result = await injector_a_v2.transform(result)

        assert len(result) == 5  # replaced, not accumulated
        tool_contents = [m.content for m in result if m.role == Role.TOOL]
        assert "b-v1" in tool_contents
        assert "a-v2" in tool_contents
        assert "a-v1" not in tool_contents


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
