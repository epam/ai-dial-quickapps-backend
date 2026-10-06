import pytest
from pydantic import ValidationError

from quickapp.common.hook_context.context import (
    CompletionHookContext,
    HookContext,
    HookMessage,
    HookResult,
    HookToolCall,
    RequestStartHookContext,
)


def _user(text: str) -> HookMessage:
    return HookMessage(role="user", content=text)


def _assistant(text: str | None, tool_calls: list[HookToolCall] | None = None) -> HookMessage:
    return HookMessage(role="assistant", content=text, tool_calls=tool_calls or [])


class TestLastUserMessage:
    def test_returns_last_user_message(self) -> None:
        ctx = HookContext(
            event="on_request_start",
            messages=[_user("first"), _assistant("a"), _user("second")],
        )
        assert ctx.last_user_message is not None
        assert ctx.last_user_message.content == "second"

    def test_none_when_absent(self) -> None:
        ctx = HookContext(event="on_request_start", messages=[_assistant("a")])
        assert ctx.last_user_message is None


class TestLastAssistantMessage:
    def test_skips_assistant_messages_with_tool_calls(self) -> None:
        call = HookToolCall(id="c1", name="read", arguments={})
        ctx = HookContext(
            event="on_completion",
            messages=[_user("q"), _assistant("final"), _assistant("", [call])],
        )
        assert ctx.last_assistant_message is not None
        assert ctx.last_assistant_message.content == "final"

    def test_empty_tool_calls_list_counts_as_final_answer(self) -> None:
        ctx = HookContext(event="on_completion", messages=[_user("q"), _assistant("done", [])])
        assert ctx.last_assistant_message is not None
        assert ctx.last_assistant_message.content == "done"

    def test_none_when_absent(self) -> None:
        ctx = HookContext(event="on_request_start", messages=[_user("q")])
        assert ctx.last_assistant_message is None


class TestFrozenAndDump:
    def test_models_are_frozen(self) -> None:
        ctx = HookContext(event="on_request_start", messages=[])
        with pytest.raises(ValidationError):
            ctx.event = "other"  # type: ignore[misc]
        with pytest.raises(ValidationError):
            HookMessage(role="user", content="x").content = "y"  # type: ignore[misc]

    def test_model_dump_includes_computed_fields(self) -> None:
        ctx = HookContext(event="on_request_start", messages=[_user("hi")])
        dumped = ctx.model_dump(mode="json")
        assert dumped["last_user_message"]["content"] == "hi"
        assert dumped["last_assistant_message"] is None
        assert dumped["messages"][0]["tool_calls"] == []


class TestEventContexts:
    def test_request_start_context_has_no_counters(self) -> None:
        ctx = RequestStartHookContext(event="on_request_start", messages=[])
        assert "iteration_count" not in ctx.model_dump()

    def test_completion_context_carries_counters(self) -> None:
        ctx = CompletionHookContext(
            event="on_completion", messages=[], iteration_count=3, total_tool_calls=5
        )
        assert ctx.iteration_count == 3
        assert ctx.total_tool_calls == 5


class TestHookResult:
    def test_defaults_and_frozen(self) -> None:
        result = HookResult(hook_name="h", content="c")
        assert result.tool_name is None
        assert result.arguments is None
        with pytest.raises(ValidationError):
            result.content = "x"  # type: ignore[misc]

    def test_carries_tool_name_and_arguments(self) -> None:
        result = HookResult(hook_name="h", content=None, tool_name="t", arguments={"a": 1})
        assert result.tool_name == "t"
        assert result.arguments == {"a": 1}
