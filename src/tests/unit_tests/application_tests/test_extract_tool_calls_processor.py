import warnings

import pytest
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
    """Tests for ExtractToolCallsFromStateProcessor."""

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
        """Test extraction of new message-based format with single tool call."""
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
        """Key test: parallel tool calls should remain in ONE assistant message."""
        msgs_setup, ctx = _make_setup()
        tc1 = make_tool_call("tc-1", "tool_a")
        tc2 = make_tool_call("tc-2", "tool_b")

        tool_history = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    tc1.model_dump(mode="json"),
                    tc2.model_dump(mode="json"),
                ],
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
        """Test multiple sequential tool call iterations."""
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
        """Test that legacy ExecutedToolCallDTO format still works with deprecation warning."""
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
        """Verify that tool_execution_history is removed from the final message's state."""
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
