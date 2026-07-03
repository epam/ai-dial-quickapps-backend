from aidial_sdk.chat_completion import Role

from quickapp.common.abstract.tool_execution_history_policy import ToolExecutionHistoryPolicy
from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_tool_response import (
    build_content_summary,
    display_url_from_attachment_url,
    merge_get_content_state,
    parse_from_state,
    parse_function_arguments,
    resolve_success_fields,
    success_response_for_history,
)


class _GetContentHistoryPolicy(ToolExecutionHistoryPolicy):
    """Strip ``custom_content.attachments`` from get_content TOOL messages.

    Once persisted, the bytes would otherwise re-surface on every subsequent
    request and undermine the lazy-load contract: a new turn should rely on
    list-tool metadata and call ``internal_attachments_get_content`` again only
    when the document is needed.

    Structured metadata is stored in ``custom_content.state``; the tool
    ``content`` string is rewritten to a human-readable summary with
    ``status_message`` so the model knows to re-call the tool.
    """

    def apply(self, history: list[dict[str, object]]) -> list[dict[str, object]]:
        tool_name_by_call_id: dict[str, str] = {}
        tool_call_arguments_by_id: dict[str, dict[str, object]] = {}
        for msg in history:
            if msg.get("role") != Role.ASSISTANT.value:
                continue
            tool_calls = msg.get("tool_calls")
            if not isinstance(tool_calls, list):
                continue
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                tool_call_id = tool_call.get("id")
                function = tool_call.get("function")
                if not isinstance(tool_call_id, str) or not isinstance(function, dict):
                    continue
                name = function.get("name")
                if name != INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME:
                    continue
                tool_name_by_call_id[tool_call_id] = name
                parsed_args = parse_function_arguments(function)
                if parsed_args is not None:
                    tool_call_arguments_by_id[tool_call_id] = parsed_args

        for msg in history:
            if msg.get("role") != Role.TOOL.value:
                continue
            tool_call_id = msg.get("tool_call_id")
            if not isinstance(tool_call_id, str):
                continue
            if tool_name_by_call_id.get(tool_call_id) != INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME:
                continue

            custom_content = msg.get("custom_content")
            if not isinstance(custom_content, dict):
                continue

            attachments = custom_content.get("attachments")
            if isinstance(attachments, list) and attachments:
                state = custom_content.get("state")
                state_dict = state if isinstance(state, dict) else {}
                tool_args = tool_call_arguments_by_id.get(tool_call_id)
                if tool_args is not None and tool_args.get("attachment_url"):
                    display_url, title, mime_type = resolve_success_fields(
                        tool_call_arguments=tool_args,
                        attachments=attachments,
                    )
                else:
                    existing = parse_from_state(state_dict)
                    if existing is not None and existing.status == "Success":
                        display_url = display_url_from_attachment_url(existing.attachment_url or "")
                        title = existing.title or ""
                        mime_type = existing.type or ""
                    else:
                        display_url, title, mime_type = resolve_success_fields(
                            tool_call_arguments=None,
                            attachments=attachments,
                        )
                response = success_response_for_history(
                    display_url=display_url,
                    title=title,
                    mime_type=mime_type,
                )
                msg["content"] = build_content_summary(response)
                custom_content["state"] = merge_get_content_state(state_dict, response)

            custom_content.pop("attachments", None)
            if not custom_content:
                msg.pop("custom_content", None)

        return history
