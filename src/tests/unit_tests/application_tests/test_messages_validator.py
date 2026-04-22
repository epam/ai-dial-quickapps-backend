"""Tests for `validate_messages_shape` — enforces `(System)? (User Assistant)* User`."""

import pytest
from aidial_sdk.chat_completion import Message, Role
from aidial_sdk.exceptions import InvalidRequestError

from quickapp.application._messages_validator import validate_messages_shape


def _msg(role: Role, content: str = "x") -> Message:
    return Message(role=role, content=content)


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


class TestEmptyInput:
    def test_empty_raises(self):
        with pytest.raises(InvalidRequestError) as exc:
            validate_messages_shape([])
        assert "must not be empty" in _display_message(exc.value)


class TestIllegalRoles:
    def test_tool_message_anywhere_raises(self):
        with pytest.raises(InvalidRequestError) as exc:
            validate_messages_shape([_msg(Role.USER), _msg(Role.TOOL), _msg(Role.USER)])
        msg = _display_message(exc.value)
        assert "role 'tool' is not allowed" in msg
        assert "index 1" in msg

    def test_system_after_index_zero_raises(self):
        with pytest.raises(InvalidRequestError) as exc:
            validate_messages_shape([_msg(Role.USER), _msg(Role.SYSTEM), _msg(Role.USER)])
        assert "role 'system' is only allowed at index 0" in _display_message(exc.value)

    def test_illegal_role_suppresses_sequence_violations(self):
        """Reporting illegal-role issues alone keeps the error list focused."""
        with pytest.raises(InvalidRequestError) as exc:
            validate_messages_shape([_msg(Role.TOOL)])
        msg = _display_message(exc.value)
        assert "role 'tool' is not allowed" in msg
        assert "expected role" not in msg


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
        assert "must end with a user message" in _display_message(exc.value)

    def test_only_system_raises(self):
        with pytest.raises(InvalidRequestError) as exc:
            validate_messages_shape([_msg(Role.SYSTEM)])
        assert "at least one user message" in _display_message(exc.value)


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
        assert "must end with a user message" in msg
        assert msg.startswith("Invalid messages array:\n- ")
        assert msg.count("\n- ") >= 2
