"""Canonical payload for get_content chat-completion recovery (message + stage UI)."""

from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_tool_response import (
    GetContentToolResponse,
)

_GET_CONTENT_RECOVERY_ERROR_TEXT = (
    "The AI model service rejected the attachment payload; the file was not forwarded."
)


def get_content_recovery_parts() -> tuple[str, dict[str, object]]:
    """Human-readable TOOL content and state fragment for BadRequest recovery."""
    return GetContentToolResponse.fail(
        message=_GET_CONTENT_RECOVERY_ERROR_TEXT,
        accepted_types=[],
    ).tool_parts()
