from aidial_sdk.chat_completion import Role

from quickapp.common.abstract.tool_execution_history_policy import ToolExecutionHistoryPolicy
from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME


class _GetContentHistoryPolicy(ToolExecutionHistoryPolicy):
    """Strip ``custom_content.attachments`` from get_content TOOL messages.

    Once persisted, the bytes would otherwise re-surface on every subsequent
    request and undermine the lazy-load contract: a new turn should rely on
    list-tool metadata and call ``internal_attachments_get_content`` again only
    when the document is needed.
    """

    def apply(self, history: list[dict[str, object]]) -> list[dict[str, object]]:
        tool_name_by_call_id: dict[str, str] = {}
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
                if isinstance(name, str):
                    tool_name_by_call_id[tool_call_id] = name

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

            custom_content.pop("attachments", None)
            if not custom_content:
                msg.pop("custom_content", None)

        return history
