"""Canonical JSON and ToolCallResult for get_content chat-completion recovery (message + stage UI)."""

import json

_GET_CONTENT_RECOVERY_ERROR_TEXT = (
    "The AI model service rejected the attachment payload; the file was not forwarded."
)


def get_content_recovery_json_string() -> str:
    """Exact TOOL message body written by get_content BadRequest recovery."""
    return json.dumps(
        {"ok": False, "error": _GET_CONTENT_RECOVERY_ERROR_TEXT},
        ensure_ascii=False,
    )
