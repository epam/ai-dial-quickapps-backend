from aidial_sdk.chat_completion import Role

from quickapp.common.abstract.tool_execution_history_policy import ToolExecutionHistoryPolicy
from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_tool_response import (
    history_strip_response,
    parse_function_arguments,
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
        get_content_call_ids: set[str] = set()
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
                if function.get("name") != INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME:
                    continue
                get_content_call_ids.add(tool_call_id)
                parsed_args = parse_function_arguments(function)
                if parsed_args is not None:
                    tool_call_arguments_by_id[tool_call_id] = parsed_args

        for msg in history:
            if msg.get("role") != Role.TOOL.value:
                continue
            tool_call_id = msg.get("tool_call_id")
            if not isinstance(tool_call_id, str) or tool_call_id not in get_content_call_ids:
                continue

            custom_content = msg.get("custom_content")
            if not isinstance(custom_content, dict):
                continue

            attachments = custom_content.get("attachments")
            if isinstance(attachments, list) and attachments:
                state = custom_content.get("state")
                state_dict = state if isinstance(state, dict) else {}
                response = history_strip_response(
                    tool_call_arguments=tool_call_arguments_by_id.get(tool_call_id),
                    attachments=attachments,
                    state=state_dict,
                )
                msg["content"] = response.content_summary()
                custom_content["state"] = response.merge_into_state(state_dict)

            custom_content.pop("attachments", None)
            if not custom_content:
                msg.pop("custom_content", None)

        return history
