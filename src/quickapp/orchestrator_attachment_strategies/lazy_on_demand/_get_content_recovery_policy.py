import json

from aidial_sdk.chat_completion import CustomContent
from aidial_sdk.chat_completion.request import Message, Role
from openai import APIError, BadRequestError

from quickapp.common.abstract.chat_completion_recovery_policy import ChatCompletionRecoveryPolicy
from quickapp.common.tool_message_utils import tool_function_name_for_tool_message
from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_recovery_payload import (
    get_content_recovery_parts,
)

_ATTACHMENT_ERROR_SIGNALS: tuple[str, ...] = (
    "attachment payload",
    "attachment type",
    "unsupported attachment",
    "invalid attachment",
    "unsupported file",
    "invalid file",
    "file type",
    "files failed to process",
    "supported types",
)


def _is_recoverable_api_error(error: Exception) -> bool:
    """True for ``BadRequestError`` and the base ``APIError`` class only.

    Other ``APIError`` subclasses (connection, rate limit, auth, 5xx, etc.) are
    left to propagate so this policy does not mask infrastructure failures.
    """
    if isinstance(error, BadRequestError):
        return True
    return type(error) is APIError


def _body_text(body: object) -> str:
    """Serialize an OpenAI error ``body`` for substring scanning.

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
    """True when ``error`` is recoverable and its message/body mentions attachments.

    The orchestrator wraps the model adapter's response; for attachment-related
    rejections the signal appears either in the ``message`` field or in the
    structured ``body``. Only ``BadRequestError`` and the base ``APIError`` are
    considered; other ``APIError`` subclasses are never recovered here.
    """
    if not _is_recoverable_api_error(error):
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

        error_content, error_state = get_content_recovery_parts()

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
                existing_state = dict(msg.custom_content.state or {})
                existing_state.update(error_state)
                msg.custom_content.state = existing_state
            else:
                msg.custom_content = CustomContent(state=error_state)
            changed = True

        return changed
