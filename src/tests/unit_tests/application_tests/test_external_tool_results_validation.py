"""Tests for validate_external_tool_results — ensures clients provide tool
results for surfaced external tool calls."""

import pytest
from aidial_sdk.chat_completion import FunctionCall, Message, Role, ToolCall
from aidial_sdk.exceptions import InvalidRequestError

from quickapp.core.application import _MessagesSetup


def _user(content: str = "hi") -> Message:
    return Message(role=Role.USER, content=content)


def _assistant_with_tools(calls: list[tuple[str, str]]) -> Message:
    """Create an assistant message with tool_calls. calls = [(id, name), ...]"""
    return Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(id=tc_id, type="function", function=FunctionCall(name=name, arguments="{}"))
            for tc_id, name in calls
        ],
    )


def _tool_msg(tool_call_id: str, content: str = "result") -> Message:
    return Message(role=Role.TOOL, content=content, tool_call_id=tool_call_id)


class TestValidateExternalToolResults:
    def test_no_external_tools_passes(self):
        messages = [_user(), _assistant_with_tools([("c1", "internal_fn")]), _user()]
        _MessagesSetup.validate_external_tool_results(messages, frozenset())

    def test_external_tools_with_correct_results_passes(self):
        messages = [
            _user(),
            _assistant_with_tools([("c1", "get_balance")]),
            _tool_msg("c1"),
        ]
        _MessagesSetup.validate_external_tool_results(messages, frozenset({"get_balance"}))

    def test_multiple_external_tools_with_all_results_passes(self):
        messages = [
            _user(),
            _assistant_with_tools([("c1", "get_balance"), ("c2", "get_name")]),
            _tool_msg("c1"),
            _tool_msg("c2"),
        ]
        _MessagesSetup.validate_external_tool_results(
            messages, frozenset({"get_balance", "get_name"})
        )

    def test_mixed_internal_and_external_only_checks_external(self):
        messages = [
            _user(),
            _assistant_with_tools([("c1", "internal_fn"), ("c2", "get_balance")]),
            _tool_msg("c2"),
        ]
        _MessagesSetup.validate_external_tool_results(messages, frozenset({"get_balance"}))

    def test_missing_external_tool_result_raises(self):
        messages = [
            _user(),
            _assistant_with_tools([("c1", "get_balance")]),
            _user("never mind"),
        ]
        with pytest.raises(InvalidRequestError) as exc:
            _MessagesSetup.validate_external_tool_results(messages, frozenset({"get_balance"}))
        msg = exc.value.display_message
        assert "get_balance" in msg
        assert "c1" in msg

    def test_missing_one_of_multiple_external_tool_results_raises(self):
        messages = [
            _user(),
            _assistant_with_tools([("c1", "get_balance"), ("c2", "get_name")]),
            _tool_msg("c1"),
            _user("only gave one result"),
        ]
        with pytest.raises(InvalidRequestError) as exc:
            _MessagesSetup.validate_external_tool_results(
                messages, frozenset({"get_balance", "get_name"})
            )
        msg = exc.value.display_message
        assert "get_name" in msg
        assert "c2" in msg

    def test_no_messages_after_assistant_with_external_tools_raises(self):
        messages = [
            _user(),
            _assistant_with_tools([("c1", "get_balance")]),
        ]
        with pytest.raises(InvalidRequestError) as exc:
            _MessagesSetup.validate_external_tool_results(messages, frozenset({"get_balance"}))
        msg = exc.value.display_message
        assert "get_balance" in msg

    def test_user_message_instead_of_tool_result_raises(self):
        messages = [
            _user("What is my balance?"),
            _assistant_with_tools([("c1", "get_balance")]),
            _user("Tell me a joke instead"),
        ]
        with pytest.raises(InvalidRequestError) as exc:
            _MessagesSetup.validate_external_tool_results(messages, frozenset({"get_balance"}))
        msg = exc.value.display_message
        assert "Missing tool result" in msg

    def test_assistant_without_tool_calls_not_affected(self):
        messages = [
            _user(),
            Message(role=Role.ASSISTANT, content="just text"),
            _user(),
        ]
        _MessagesSetup.validate_external_tool_results(messages, frozenset({"get_balance"}))

    def test_tool_results_followed_by_user_passes(self):
        messages = [
            _user(),
            _assistant_with_tools([("c1", "get_balance")]),
            _tool_msg("c1"),
            _user("thanks, now what?"),
        ]
        _MessagesSetup.validate_external_tool_results(messages, frozenset({"get_balance"}))
