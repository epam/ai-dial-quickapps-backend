"""Helpers to identify the source tool of a form from conversation history.

A form is identified by content, not by state markers: the tool message carrying
``custom_content.form_schema`` holds the ``tool_call_id``, and the assistant message
with that tool call gives the tool name.
"""

from aidial_sdk.chat_completion import Message, Role

from quickapp.config.application import ApplicationConfig
from quickapp.config.toolsets.deployment import DeploymentToolSet


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


def find_tool_conversation_mode(app_config: ApplicationConfig, tool_name: str | None):
    """conversation_mode of the named tool in the app config, if identifiable."""
    if tool_name is None:
        return None
    for ts in app_config.tool_sets or []:
        if isinstance(ts, DeploymentToolSet):
            for tool in ts.tools:
                if not getattr(tool, "enabled", True):
                    continue
                fn = getattr(getattr(tool, "open_ai_tool", None), "function", None)
                if getattr(fn, "name", None) == tool_name:
                    return getattr(tool, "conversation_mode", None)
    return None


def is_resumable(conversation_mode) -> bool:
    return bool(conversation_mode is not None and getattr(conversation_mode, "resumable", False))
