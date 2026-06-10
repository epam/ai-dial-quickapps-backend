import json

from aidial_sdk.chat_completion.request import Message, Role
from openai import BadRequestError

from quickapp.common.abstract.chat_completion_recovery_policy import ChatCompletionRecoveryPolicy
from quickapp.common.get_content_recovery_payload import get_content_recovery_json_string
from quickapp.common.tool_message_utils import tool_function_name_for_tool_message
from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME

_ATTACHMENT_ERROR_SIGNALS: tuple[str, ...] = (
    "attachment payload",
    "attachment type",
    "unsupported attachment",
    "invalid attachment",
    "unsupported file",
    "invalid file",
    "input_attachment_types",
    "image_url",
    "file type",
)


def _body_text(body: object) -> str:
    """Serialize a ``BadRequestError.body`` for substring scanning.

    The OpenAI SDK populates ``body`` as ``None``, a ``str``, or a parsed JSON
    ``dict`` depending on the upstream error path. For dicts, ``json.dumps`` is
    used instead of ``str(...)`` so the substring scan applies to actual JSON
    content (e.g. ``"unsupported file"`` inside a nested ``error.message``)
    rather than a Python ``repr`` of the structure.
    """
    if body is None:
        return ""
    if isinstance(body, str):
        return body
    try:
        return json.dumps(body, default=str)
    except (TypeError, ValueError):
        return ""


def _looks_like_attachment_error(error: Exception) -> bool:
    """True when ``error`` is a BadRequest whose message/body mentions attachment payloads.

    The orchestrator wraps the model adapter's response; for attachment-related
    rejections the signal appears either in the ``message`` field or in the
    structured ``body``. Non-BadRequest errors (RateLimit, 5xx, connection) never
    indicate the attachment payload is at fault, so they are rejected outright.
    """
    if not isinstance(error, BadRequestError):
        return False
    haystack = f"{error.message} {_body_text(getattr(error, 'body', None))}".lower()
    return any(signal in haystack for signal in _ATTACHMENT_ERROR_SIGNALS)


class _GetContentRecoveryPolicy(ChatCompletionRecoveryPolicy):
    """Rewrites get-content TOOL payloads to an error shape and strips attachments."""

    def try_recover(self, messages: list[Message], error: Exception) -> bool:
        if not _looks_like_attachment_error(error):
            return False
        turn_start: int | None = None
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].role == Role.USER:
                turn_start = i + 1
                break
        if turn_start is None:
            return False

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
