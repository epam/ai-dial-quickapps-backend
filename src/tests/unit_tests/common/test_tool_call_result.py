"""The ``is_error`` flag is persisted on the TOOL message's state and read back from it."""

from aidial_sdk.chat_completion import CustomContent, Message, Role

from quickapp.common.tool_call_result import (
    IS_ERROR_STATE_KEY,
    ToolCallResult,
    tool_call_result_from_tool_message,
)


def _result(**kwargs) -> ToolCallResult:
    return ToolCallResult(
        tool_call_id="call-1", content="body", content_type="text/plain", **kwargs
    )


class TestToMessageWritesFlag:
    def test_error_result_sets_flag_on_empty_state(self):
        message = _result(is_error=True).to_tool_message()

        assert message.role == Role.TOOL
        assert message.custom_content is not None
        assert message.custom_content.state == {IS_ERROR_STATE_KEY: True}

    def test_error_result_merges_into_existing_state(self):
        result = _result(is_error=True, state={"other": 1})

        message = result.to_tool_message()

        assert message.custom_content is not None
        assert message.custom_content.state == {"other": 1, IS_ERROR_STATE_KEY: True}

    def test_error_result_does_not_mutate_the_result_state(self):
        result = _result(is_error=True, state={"other": 1})

        result.to_tool_message()

        assert result.state == {"other": 1}

    def test_success_result_leaves_state_none(self):
        message = _result().to_tool_message()

        assert message.custom_content is not None
        assert message.custom_content.state is None

    def test_success_result_leaves_existing_state_untouched(self):
        message = _result(state={"other": 1}).to_tool_message()

        assert message.custom_content is not None
        assert message.custom_content.state == {"other": 1}


class TestFromMessageReadsFlag:
    @staticmethod
    def _message(state: dict | None) -> Message:
        return Message(
            role=Role.TOOL,
            content="body",
            tool_call_id="call-1",
            custom_content=CustomContent(state=state),
        )

    def test_flag_true_is_read_back(self):
        result = tool_call_result_from_tool_message(self._message({IS_ERROR_STATE_KEY: True}))

        assert result.is_error is True

    def test_missing_flag_is_not_an_error(self):
        assert tool_call_result_from_tool_message(self._message({"other": 1})).is_error is False

    def test_no_state_is_not_an_error(self):
        assert tool_call_result_from_tool_message(self._message(None)).is_error is False

    def test_only_a_literal_true_counts(self):
        result = tool_call_result_from_tool_message(self._message({IS_ERROR_STATE_KEY: "true"}))

        assert result.is_error is False

    def test_message_without_custom_content_is_not_an_error(self):
        message = Message(role=Role.TOOL, content="body", tool_call_id="call-1")

        assert tool_call_result_from_tool_message(message).is_error is False


class TestRoundTrip:
    def test_error_survives_round_trip(self):
        original = _result(is_error=True, state={"other": 1})

        restored = tool_call_result_from_tool_message(original.to_tool_message())

        assert restored.is_error is True
        assert restored.content == "body"
        assert restored.state == {"other": 1, IS_ERROR_STATE_KEY: True}

    def test_success_survives_round_trip(self):
        restored = tool_call_result_from_tool_message(_result().to_tool_message())

        assert restored.is_error is False
