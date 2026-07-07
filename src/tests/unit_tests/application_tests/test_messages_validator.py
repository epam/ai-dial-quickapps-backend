"""Tests for `validate_messages_shape` — enforces message sequence contract."""

import pytest
from aidial_sdk.chat_completion import FunctionCall, Message, Role, ToolCall
from aidial_sdk.exceptions import InvalidRequestError

from quickapp.core.application import validate_messages_shape


def _msg(role: Role, content: str = "x") -> Message:
    return Message(role=role, content=content)


def _assistant_with_tools(*tool_call_ids: str) -> Message:
    return Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(
                id=tc_id, type="function", function=FunctionCall(name=f"fn_{i}", arguments="{}")
            )
            for i, tc_id in enumerate(tool_call_ids)
        ],
    )


def _tool_msg(tool_call_id: str, content: str = "result") -> Message:
    return Message(role=Role.TOOL, content=content, tool_call_id=tool_call_id)


def _display_message(exc: InvalidRequestError) -> str:
    display = exc.display_message
    assert display is not None
    return display


class TestValidShapes:
    def test_single_user_message(self):
        validate_messages_shape([_msg(Role.USER)])

    def test_system_plus_user(self):
        validate_messages_shape([_msg(Role.SYSTEM), _msg(Role.USER)])

    def test_one_turn(self):
        validate_messages_shape([_msg(Role.USER), _msg(Role.ASSISTANT), _msg(Role.USER)])

    def test_system_plus_multi_turn(self):
        validate_messages_shape(
            [
                _msg(Role.SYSTEM),
                _msg(Role.USER),
                _msg(Role.ASSISTANT),
                _msg(Role.USER),
                _msg(Role.ASSISTANT),
                _msg(Role.USER),
            ]
        )

    def test_assistant_with_tool_calls_followed_by_tool_messages(self):
        validate_messages_shape(
            [
                _msg(Role.USER),
                _assistant_with_tools("call_1"),
                _tool_msg("call_1"),
            ]
        )

    def test_assistant_with_multiple_tool_calls_followed_by_tool_messages(self):
        validate_messages_shape(
            [
                _msg(Role.USER),
                _assistant_with_tools("call_1", "call_2"),
                _tool_msg("call_1"),
                _tool_msg("call_2"),
            ]
        )

    def test_tool_results_followed_by_user_message(self):
        validate_messages_shape(
            [
                _msg(Role.USER),
                _assistant_with_tools("call_1"),
                _tool_msg("call_1"),
                _msg(Role.USER),
            ]
        )

    def test_multi_turn_with_tool_calls(self):
        validate_messages_shape(
            [
                _msg(Role.USER),
                _assistant_with_tools("call_1"),
                _tool_msg("call_1"),
                _msg(Role.USER),
                _msg(Role.ASSISTANT),
                _msg(Role.USER),
            ]
        )


class TestEmptyInput:
    def test_empty_raises(self):
        with pytest.raises(InvalidRequestError) as exc:
            validate_messages_shape([])
        assert "must not be empty" in _display_message(exc.value)


class TestIllegalRoles:
    def test_tool_message_without_preceding_assistant_raises(self):
        with pytest.raises(InvalidRequestError) as exc:
            validate_messages_shape([_msg(Role.USER), _tool_msg("call_1")])
        msg = _display_message(exc.value)
        assert "only allowed immediately after an assistant message with tool_calls" in msg

    def test_tool_after_assistant_without_tool_calls_raises(self):
        with pytest.raises(InvalidRequestError) as exc:
            validate_messages_shape([_msg(Role.USER), _msg(Role.ASSISTANT), _tool_msg("call_1")])
        msg = _display_message(exc.value)
        assert "only allowed immediately after an assistant message with tool_calls" in msg

    def test_system_after_index_zero_raises(self):
        with pytest.raises(InvalidRequestError) as exc:
            validate_messages_shape([_msg(Role.USER), _msg(Role.SYSTEM), _msg(Role.USER)])
        assert "role 'system' is only allowed at index 0" in _display_message(exc.value)


class TestSequenceRules:
    def test_two_consecutive_user_raises(self):
        with pytest.raises(InvalidRequestError) as exc:
            validate_messages_shape([_msg(Role.USER), _msg(Role.USER)])
        msg = _display_message(exc.value)
        assert "expected role 'assistant'" in msg
        assert "index 1" in msg

    def test_two_consecutive_assistant_raises(self):
        with pytest.raises(InvalidRequestError) as exc:
            validate_messages_shape(
                [
                    _msg(Role.USER),
                    _msg(Role.ASSISTANT),
                    _msg(Role.ASSISTANT),
                    _msg(Role.USER),
                ]
            )
        msg = _display_message(exc.value)
        assert "expected role 'user'" in msg
        assert "index 2" in msg

    def test_first_message_assistant_raises(self):
        with pytest.raises(InvalidRequestError) as exc:
            validate_messages_shape([_msg(Role.ASSISTANT), _msg(Role.USER)])
        msg = _display_message(exc.value)
        assert "expected role 'user'" in msg
        assert "index 0" in msg

    def test_first_message_assistant_after_system_raises(self):
        with pytest.raises(InvalidRequestError) as exc:
            validate_messages_shape([_msg(Role.SYSTEM), _msg(Role.ASSISTANT), _msg(Role.USER)])
        msg = _display_message(exc.value)
        assert "expected role 'user'" in msg
        assert "index 1" in msg

    def test_trailing_assistant_raises(self):
        with pytest.raises(InvalidRequestError) as exc:
            validate_messages_shape([_msg(Role.USER), _msg(Role.ASSISTANT)])
        assert "must end with a user or tool message" in _display_message(exc.value)

    def test_only_system_raises(self):
        with pytest.raises(InvalidRequestError) as exc:
            validate_messages_shape([_msg(Role.SYSTEM)])
        assert "at least one user message" in _display_message(exc.value)


class TestToolCallIdViolations:
    def test_tool_message_with_wrong_tool_call_id_raises(self):
        with pytest.raises(InvalidRequestError) as exc:
            validate_messages_shape(
                [
                    _msg(Role.USER),
                    _assistant_with_tools("call_1"),
                    _tool_msg("wrong_id"),
                ]
            )
        msg = _display_message(exc.value)
        assert "tool_call_id 'wrong_id' does not match" in msg

    def test_tool_message_without_tool_call_id_raises(self):
        with pytest.raises(InvalidRequestError) as exc:
            validate_messages_shape(
                [
                    _msg(Role.USER),
                    _assistant_with_tools("call_1"),
                    Message(role=Role.TOOL, content="result"),
                ]
            )
        msg = _display_message(exc.value)
        assert "must have a tool_call_id" in msg


class TestMultipleViolations:
    def test_multiple_issues_are_all_reported(self):
        with pytest.raises(InvalidRequestError) as exc:
            validate_messages_shape(
                [
                    _msg(Role.USER),
                    _msg(Role.USER),
                    _msg(Role.ASSISTANT),
                    _msg(Role.ASSISTANT),
                ]
            )
        msg = _display_message(exc.value)
        assert "index 1" in msg
        assert "index 3" in msg
        assert "must end with a user or tool message" in msg
        assert msg.startswith("Invalid messages array:\n- ")
        assert msg.count("\n- ") >= 2
