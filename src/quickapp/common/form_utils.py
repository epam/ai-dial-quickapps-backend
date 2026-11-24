"""Helpers to identify the source tool of a form from conversation history.

A form is identified by content, not by state markers. The client echoes the assistant
message back with ``custom_content.form_schema`` — that is the schema the UI actually
rendered — plus its ``tool_calls`` (the initiator). The tool message with the matching
``form_schema`` and ``tool_call_id`` identifies the generator. Matching the two schemas
by content links initiator ↔ generator unambiguously.
"""

from typing import Any

from aidial_sdk.chat_completion import Message, Role

from quickapp.common.staged_base_tool import StagedBaseTool


def _form_schema_of(message: Message) -> dict[str, Any] | None:
    cc = message.custom_content
    if cc is not None and isinstance(cc.form_schema, dict):
        return cc.form_schema
    return None


def form_source_tool_name_before(messages: list[Message], index: int) -> str | None:
    """Name of the tool that *initiated* the form the client is currently filling.

    Resolution, from ``messages[:index]``:

    1. Find the latest **assistant** message carrying ``custom_content.form_schema``
       (the schema the client rendered) — within the latest turn segment (segments are
       split by user messages; the SDK allows one form per choice, so the first such
       assistant message in the segment is the one shown).
    2. Match a **tool** message whose ``custom_content.form_schema`` equals it by content
       and whose ``tool_call_id`` appears in that assistant message's ``tool_calls`` —
       that tool is the generator; the assistant's tool call name is the initiator.
    3. Return the initiator's name (the tool call that requested the form). When no
       assistant message carries a schema, fall back to the tool message alone
       (tool_call_id → assistant tool call name).
    """
    history = messages[:index]
    segment_starts = [0] + [i for i, m in enumerate(history) if m.role == Role.USER]
    for seg_start in reversed(segment_starts):
        segment = history[seg_start:]
        # 1. latest assistant message with a schema in this segment (first one wins)
        assistant_msg = None
        shown_schema = None
        for message in segment:
            if message.role != Role.ASSISTANT:
                continue
            schema = _form_schema_of(message)
            if schema is not None:
                assistant_msg = message
                shown_schema = schema
                break
        if assistant_msg is not None and assistant_msg.tool_calls and shown_schema is not None:
            call_ids = {tc.id for tc in assistant_msg.tool_calls}
            # 2. tool message with the same schema and a matching tool_call_id → generator
            for message in segment:
                if message.role != Role.TOOL or not message.tool_call_id:
                    continue
                if message.tool_call_id not in call_ids:
                    continue
                if _form_schema_of(message) == shown_schema:
                    # initiator = the tool call in the assistant message
                    for tc in assistant_msg.tool_calls:
                        if tc.id == message.tool_call_id:
                            return tc.function.name
            # schema matched but no tool message with same content — still return initiator
            return assistant_msg.tool_calls[0].function.name
        # 3. fallback: tool message with any schema → tool_call_id → assistant tool call
        for message in segment:
            if message.role != Role.TOOL or not message.tool_call_id:
                continue
            if _form_schema_of(message) is not None:
                for am in segment:
                    if am.role != Role.ASSISTANT or not am.tool_calls:
                        continue
                    for tc in am.tool_calls:
                        if tc.id == message.tool_call_id:
                            return tc.function.name
                break
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
