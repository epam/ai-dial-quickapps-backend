"""``ToolCallResult.to_tool_message`` / ``tool_call_result_from_tool_message`` roundtrip."""

from aidial_sdk.chat_completion import Message, Role

from quickapp.common.tool_call_result import ToolCallResult, tool_call_result_from_tool_message


def _result(**kwargs) -> ToolCallResult:
    defaults = {"tool_call_id": "tc-1", "content": "out", "content_type": "text/plain"}
    return ToolCallResult(**{**defaults, **kwargs})


def test_to_tool_message_carries_form_schema():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    msg = _result(form_schema=schema).to_tool_message()

    assert msg.role == Role.TOOL
    assert msg.tool_call_id == "tc-1"
    assert msg.custom_content is not None
    assert msg.custom_content.form_schema == schema


def test_to_tool_message_without_form_schema():
    msg = _result().to_tool_message()

    assert msg.custom_content is not None
    assert msg.custom_content.form_schema is None


def test_roundtrip_preserves_form_schema():
    schema = {"type": "object"}
    msg = _result(form_schema=schema).to_tool_message()

    restored = tool_call_result_from_tool_message(msg)

    assert restored.form_schema == schema


def test_from_tool_message_without_custom_content():
    msg = Message(role=Role.TOOL, content="out", tool_call_id="tc-1")

    restored = tool_call_result_from_tool_message(msg)

    assert restored.form_schema is None
