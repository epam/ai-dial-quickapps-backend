"""Helpers to identify the source tool of a form from conversation history.

A form is identified by content, not by state markers: the tool message carrying
``custom_content.form_schema`` holds the ``tool_call_id``, and the assistant message
with that tool call gives the tool name.
"""

from typing import Any

from aidial_sdk.chat_completion import Message, Role

from quickapp.common.staged_base_tool import StagedBaseTool


def _form_schema_of(message: Message) -> dict[str, Any] | None:
    cc = message.custom_content
    if cc is not None and isinstance(cc.form_schema, dict):
        return cc.form_schema
    return None


def last_user_message_index(messages: list[Message]) -> int | None:
    """Index of the last USER message, or None.

    Used as the history cutoff when resolving the form's source tool and as the source
    of the current ``form_value``: tool results produced later in the same request must
    not shadow the form the user actually submitted.
    """
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == Role.USER:
            return i
    return None


def form_value_of(message: Message) -> Any | None:
    """``custom_content.form_value`` of a message, if present."""
    if message.custom_content is not None:
        return message.custom_content.form_value
    return None


def _tool_name_by_call_id(messages: list[Message]) -> dict[str, str]:
    """Map tool_call_id → tool name from all assistant messages."""
    result: dict[str, str] = {}
    for message in messages:
        if message.role != Role.ASSISTANT or not message.tool_calls:
            continue
        for tc in message.tool_calls:
            result[tc.id] = tc.function.name
    return result


def _first_form_call_id_in_segment(segment: list[Message]) -> str | None:
    """tool_call_id of the first tool message in the segment carrying a form_schema."""
    for message in segment:
        if message.role != Role.TOOL or not message.tool_call_id:
            continue
        if _form_schema_of(message) is not None:
            return message.tool_call_id
    return None


def form_source_tool_name_before(messages: list[Message], index: int) -> str | None:
    """Name of the tool whose form the client is currently filling, from ``messages[:index]``.

    Turn segments are split by user messages; the client renders the form from the
    latest segment that carried one, and within a segment the orchestrator propagates
    only the first schema (SDK allows one ``set_form_schema`` per choice). So: scan
    segments newest-first, take the first tool message with a form_schema in the latest
    form-bearing segment, and resolve its tool name via tool_call_id.
    """
    history = messages[:index]
    call_id_to_name = _tool_name_by_call_id(history)
    segment_starts = [0] + [i for i, m in enumerate(history) if m.role == Role.USER]
    for seg_start in reversed(segment_starts):
        call_id = _first_form_call_id_in_segment(history[seg_start:])
        if call_id is not None:
            return call_id_to_name.get(call_id)
    return None


def find_tool(tools: list[StagedBaseTool], tool_name: str | None) -> StagedBaseTool | None:
    """Runtime tool instance with the given LLM-facing name, or None."""
    if tool_name is None:
        return None
    for tool in tools:
        if tool.openai_function_name() == tool_name:
            return tool
    return None


def find_tool_conversation_mode(tools: list[StagedBaseTool], tool_name: str | None) -> Any | None:
    """``conversation_mode`` of the runtime tool instance with the given LLM-facing
    name, or None when no such tool exists.

    Resolved against live tool instances (not the static config), so it covers
    ``deployment-tool``, ``dial-deployment-simple`` and ``dial-app`` alike — all of
    them expand to a ``DialDeploymentTool`` at runtime.
    """
    tool = find_tool(tools, tool_name)
    if tool is None:
        return None
    return getattr(tool.tool_config, "conversation_mode", None)


def is_resumable(conversation_mode: Any | None) -> bool:
    return bool(conversation_mode is not None and getattr(conversation_mode, "resumable", False))
