from aidial_sdk.chat_completion.request import FunctionCall, Message, Role, ToolCall

from quickapp.common.tool_message_utils import tool_function_name_for_tool_message


def test_tool_function_name_resolves_from_prior_assistant_tool_calls() -> None:
    assistant = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(
                id="call-1",
                type="function",
                function=FunctionCall(name="my_tool", arguments="{}"),
            )
        ],
    )
    tool_msg = Message(role=Role.TOOL, content="{}", tool_call_id="call-1")
    messages = [assistant, tool_msg]
    assert tool_function_name_for_tool_message(messages, 1) == "my_tool"


def test_tool_function_name_non_tool_returns_none() -> None:
    messages = [Message(role=Role.USER, content="hi")]
    assert tool_function_name_for_tool_message(messages, 0) is None


def test_tool_function_name_missing_tool_call_id_returns_none() -> None:
    assistant = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(
                id="call-1",
                type="function",
                function=FunctionCall(name="x", arguments="{}"),
            )
        ],
    )
    tool_msg = Message(role=Role.TOOL, content="{}", tool_call_id=None)
    messages = [assistant, tool_msg]
    assert tool_function_name_for_tool_message(messages, 1) is None


def test_tool_function_name_no_matching_assistant_returns_none() -> None:
    tool_msg = Message(role=Role.TOOL, content="{}", tool_call_id="orphan")
    messages = [tool_msg]
    assert tool_function_name_for_tool_message(messages, 0) is None
