"""Helpers to identify the source tool of a form from conversation history.

A form is identified by content, not by state markers: the tool message carrying
``custom_content.form_schema`` holds the ``tool_call_id``, and the assistant message
with that tool call gives the tool name.
"""

from typing import Any

from aidial_sdk.chat_completion import Message, Role

from quickapp.common.staged_base_tool import StagedBaseTool


def form_source_tool_name_before(messages: list[Message], index: int) -> str | None:
    """Name of the tool whose form the client is currently filling, resolved from
    ``messages[:index]``.

    The orchestrator sends only the *first* form_schema of a turn to the client
    (SDK allows one ``set_form_schema`` per choice), and the client renders the form
    from the *latest* turn that carried one. So: scan turn segments (split by user
    messages) from the end, and within the latest segment carrying a form_schema take
    the first one. Returns None when no tool message before ``index`` carries a
    form_schema.
    """
    history = messages[:index]
    # segment boundaries: each user message starts a new turn segment; the leading
    # segment (before the first user message) is also a segment
    segment_starts = [0] + [i for i, m in enumerate(history) if m.role == Role.USER]
    for seg_start in reversed(segment_starts):
        tool_call_id: str | None = None
        for message in history[seg_start:]:
            if message.role != Role.TOOL or not message.tool_call_id:
                continue
            cc = message.custom_content
            if cc is not None and isinstance(cc.form_schema, dict):
                tool_call_id = message.tool_call_id
                break  # first form within the latest form-bearing turn wins
        if tool_call_id is None:
            continue
        for message in history[seg_start:]:
            if message.role != Role.ASSISTANT or not message.tool_calls:
                continue
            for tc in message.tool_calls:
                if tc.id == tool_call_id:
                    return tc.function.name
    return None


def find_tool_conversation_mode(tools: list[StagedBaseTool], tool_name: str | None) -> Any | None:
    """``conversation_mode`` of the runtime tool instance with the given LLM-facing
    name, or None when no such tool exists.

    Resolved against live tool instances (not the static config), so it covers
    ``deployment-tool``, ``dial-deployment-simple`` and ``dial-app`` alike — all of
    them expand to a ``DialDeploymentTool`` at runtime.
    """
    if tool_name is None:
        return None
    for tool in tools:
        if tool.openai_function_name() == tool_name:
            return getattr(tool.tool_config, "conversation_mode", None)
    return None


def is_resumable(conversation_mode: Any | None) -> bool:
    return bool(conversation_mode is not None and getattr(conversation_mode, "resumable", False))
