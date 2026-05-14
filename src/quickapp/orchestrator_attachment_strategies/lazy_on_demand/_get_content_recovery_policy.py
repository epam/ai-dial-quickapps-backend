from aidial_sdk.chat_completion.request import Message, Role

from quickapp.common.abstract.chat_completion_recovery_policy import ChatCompletionRecoveryPolicy
from quickapp.common.get_content_recovery_payload import get_content_recovery_json_string
from quickapp.common.tool_message_utils import tool_function_name_for_tool_message
from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME


class _GetContentRecoveryPolicy(ChatCompletionRecoveryPolicy):
    """Rewrites get-content TOOL payloads to an error shape and strips attachments."""

    def try_recover(self, messages: list[Message], error: Exception) -> bool:
        del error  # Recovery depends on conversation payload, not error payload.
        turn_start = 0
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].role == Role.USER:
                turn_start = i + 1
                break

        error_content = get_content_recovery_json_string()

        changed = False
        for i in range(turn_start, len(messages)):
            msg = messages[i]
            if msg.role != Role.TOOL:
                continue
            if (
                tool_function_name_for_tool_message(messages, i)
                != INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
            ):
                continue
            msg.content = error_content
            if msg.custom_content is not None:
                msg.custom_content.attachments = None
            changed = True

        return changed
