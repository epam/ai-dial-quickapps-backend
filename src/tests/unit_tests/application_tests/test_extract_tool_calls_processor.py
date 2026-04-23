import warnings

import pytest
from aidial_sdk.chat_completion import CustomContent, FunctionCall, ToolCall
from aidial_sdk.chat_completion.request import Message, Role

from quickapp.agent.models import TOOL_EXECUTION_HISTORY
from quickapp.application._messages_setup import _MessagesSetup


def make_tool_call(id: str, name: str = "test_tool", arguments: str = "{}") -> ToolCall:
    return ToolCall(id=id, type="function", function=FunctionCall(name=name, arguments=arguments))


class TestExtractToolCallsFromStateProcessor:
    """Tests for ExtractToolCallsFromStateProcessor."""

    @pytest.mark.asyncio
    async def test_empty_messages_returns_empty(self):
        msgs_setup = _MessagesSetup([])
        result = await msgs_setup.setup([])
        assert result == []

    @pytest.mark.asyncio
    async def test_messages_without_state_unchanged(self):
        msgs_setup = _MessagesSetup([])
        messages = [
            Message(role=Role.USER, content="hello"),
            Message(role=Role.ASSISTANT, content="hi there"),
        ]

        result = await msgs_setup.setup(messages)

        assert len(result) == 2
        assert result[0].role == Role.USER
        assert result[1].role == Role.ASSISTANT

    @pytest.mark.asyncio
    async def test_message_without_tool_history_unchanged(self):
        msgs_setup = _MessagesSetup([])
        messages = [
            Message(
                role=Role.ASSISTANT,
                content="response",
                custom_content=CustomContent(state={"other_key": "value"}),
            )
        ]

        result = await msgs_setup.setup(messages)

        assert len(result) == 1
        assert result[0].content == "response"

    @pytest.mark.asyncio
    async def test_new_format_single_tool_call(self):
        """Test extraction of new message-based format with single tool call."""
        msgs_setup = _MessagesSetup([])
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

        result = await msgs_setup.setup(messages)

        # Should have: ASSISTANT (from history), TOOL (from history), ASSISTANT (final)
        assert len(result) == 3
        assert result[0].role == Role.ASSISTANT
        assert len(result[0].tool_calls) == 1
        assert result[0].tool_calls[0].id == "tc-1"
        assert result[1].role == Role.TOOL
        assert result[1].content == "tool output"
        assert result[1].tool_call_id == "tc-1"
        assert result[2].role == Role.ASSISTANT
        assert result[2].content == "final response"

    @pytest.mark.asyncio
    async def test_new_format_parallel_tool_calls_preserved(self):
        """Key test: parallel tool calls should remain in ONE assistant message."""
        msgs_setup = _MessagesSetup([])
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

        result = await msgs_setup.setup(messages)

        # Should have: ASSISTANT (with 2 tool_calls), TOOL, TOOL, ASSISTANT (final)
        assert len(result) == 4
        assert result[0].role == Role.ASSISTANT
        assert len(result[0].tool_calls) == 2
        assert result[0].tool_calls[0].id == "tc-1"
        assert result[0].tool_calls[1].id == "tc-2"
        assert result[1].role == Role.TOOL
        assert result[1].tool_call_id == "tc-1"
        assert result[2].role == Role.TOOL
        assert result[2].tool_call_id == "tc-2"
        assert result[3].role == Role.ASSISTANT
        assert result[3].content == "done"

    @pytest.mark.asyncio
    async def test_new_format_multiple_iterations(self):
        """Test multiple sequential tool call iterations."""
        msgs_setup = _MessagesSetup([])
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

        result = await msgs_setup.setup(messages)

        # 4 from history + 1 final = 5 messages
        assert len(result) == 5
        assert result[0].role == Role.ASSISTANT
        assert result[0].tool_calls[0].id == "tc-1"
        assert result[1].role == Role.TOOL
        assert result[2].role == Role.ASSISTANT
        assert result[2].tool_calls[0].id == "tc-2"
        assert result[3].role == Role.TOOL
        assert result[4].role == Role.ASSISTANT
        assert result[4].content == "final"

    @pytest.mark.asyncio
    async def test_legacy_format_backward_compatibility(self):
        """Test that legacy ExecutedToolCallDTO format still works with deprecation warning."""
        msgs_setup = _MessagesSetup([])
        tc = make_tool_call("tc-1", "my_tool")

        # Legacy format: list of ExecutedToolCallDTO dicts
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
            result = await msgs_setup.setup(messages)

            # Should emit deprecation warning about legacy tool_execution_history format
            deprecation_warnings = [
                x
                for x in w
                if issubclass(x.category, DeprecationWarning)
                and "tool_execution_history" in str(x.message).lower()
            ]
            assert len(deprecation_warnings) == 1
            assert "deprecated" in str(deprecation_warnings[0].message).lower()

        # Should still produce correct output
        assert len(result) == 3
        assert result[0].role == Role.ASSISTANT
        assert result[0].tool_calls[0].id == "tc-1"
        assert result[1].role == Role.TOOL
        assert result[2].role == Role.ASSISTANT

    @pytest.mark.asyncio
    async def test_tool_history_removed_from_final_message_state(self):
        """Verify that tool_execution_history is removed from the final message's state."""
        msgs_setup = _MessagesSetup([])
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

        result = await msgs_setup.setup(messages)

        # Final message should not have tool_execution_history but keep other state
        final_msg = result[-1]
        assert final_msg.custom_content is not None
        assert final_msg.custom_content.state is not None
        assert TOOL_EXECUTION_HISTORY not in final_msg.custom_content.state
        assert final_msg.custom_content.state.get("other_key") == "preserved"

    def test_is_legacy_format_detection(self):
        """Test format detection helper."""
        # Legacy format has "tool_call" key
        legacy = [{"tool_call": {}, "tool_execution_result": {}}]
        assert _MessagesSetup._is_legacy_format(legacy) is True

        # New format has "role" key
        new = [{"role": "assistant", "content": ""}]
        assert _MessagesSetup._is_legacy_format(new) is False

        # Empty list
        assert _MessagesSetup._is_legacy_format([]) is False
