"""Structured payloads for ``internal_attachments_get_content`` TOOL messages.

Human-readable summaries live in ``content``; canonical structured data lives in
``custom_content.state[GET_CONTENT_RESPONSE_STATE_KEY]``.
"""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from quickapp.common.attachment_processing_utils import normalize_attachment_url_argument
from quickapp.common.file_reference_pattern import FILE_PATTERN, to_file_url_reference
from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME

GetContentStatus = Literal["Success", "Fail"]

GET_CONTENT_RESPONSE_STATE_KEY = "_get_content_response"

HISTORY_ATTACHMENT_REMOVED_STATUS_MESSAGE = (
    "The file attachment payload was removed from saved history to save context. "
    f"Call {INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME} again with attachment_url "
    "when the content. Do not ask the user to re-upload."
)


class GetContentToolResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: GetContentStatus
    attachment_url: str | None = None
    title: str | None = None
    type: str | None = None
    status_message: str | None = None
    accepted_types: list[str] | None = None

    def to_state_entry(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude_none=True)


def model_facing_attachment_url(raw: str) -> str:
    """Return a ``file:url::...`` reference suitable for ``attachment_url`` tool args."""
    value = raw.strip()
    if not value:
        return ""
    if FILE_PATTERN.match(value):
        return value
    return to_file_url_reference(normalize_attachment_url_argument(value))


def display_url_from_attachment_url(raw: str) -> str:
    """Normalize a model-facing ``file:url::...`` reference to a bare display url."""
    value = raw.strip()
    if not value:
        return ""
    match = FILE_PATTERN.match(value)
    if match:
        bare = match.group("file_url") or ""
        return normalize_attachment_url_argument(bare) if bare else ""
    return normalize_attachment_url_argument(value)


def success_response(*, display_url: str, title: str, mime_type: str) -> GetContentToolResponse:
    return GetContentToolResponse(
        status="Success",
        attachment_url=model_facing_attachment_url(display_url),
        title=title,
        type=mime_type,
    )


def success_response_for_history(
    *,
    display_url: str,
    title: str,
    mime_type: str,
) -> GetContentToolResponse:
    return GetContentToolResponse(
        status="Success",
        attachment_url=model_facing_attachment_url(display_url),
        title=title,
        type=mime_type,
        status_message=HISTORY_ATTACHMENT_REMOVED_STATUS_MESSAGE,
    )


def fail_response(*, message: str, accepted_types: list[str]) -> GetContentToolResponse:
    return GetContentToolResponse(
        status="Fail",
        status_message=message,
        accepted_types=accepted_types,
    )


def build_content_summary(response: GetContentToolResponse) -> str:
    """Return the human-readable TOOL ``content`` string for the orchestrator model."""
    if response.status == "Fail":
        parts = [f"Failed to load attachment: {response.status_message or 'Unknown error'}."]
        if response.accepted_types:
            parts.append(f"Accepted MIME types: {', '.join(response.accepted_types)}.")
        return " ".join(parts)

    title = response.title or "file"
    mime = response.type or "application/octet-stream"
    url = response.attachment_url or ""
    lines = [f'Loaded file "{title}" ({mime}) from {url}.']
    if response.status_message:
        lines.append(response.status_message)
    return "\n".join(lines)


def build_tool_result_parts(
    response: GetContentToolResponse,
) -> tuple[str, dict[str, object]]:
    """Return ``(content, state_fragment)`` for a get-content ``ToolCallResult``."""
    return build_content_summary(response), {
        GET_CONTENT_RESPONSE_STATE_KEY: response.to_state_entry(),
    }


def merge_get_content_state(
    existing: dict[str, object] | None,
    response: GetContentToolResponse,
) -> dict[str, object]:
    merged = dict(existing or {})
    merged[GET_CONTENT_RESPONSE_STATE_KEY] = response.to_state_entry()
    return merged


def parse_from_state(state: object) -> GetContentToolResponse | None:
    """Read structured get-content data from ``custom_content.state``."""
    if not isinstance(state, dict):
        return None
    raw = state.get(GET_CONTENT_RESPONSE_STATE_KEY)
    if raw is None:
        return None
    try:
        return GetContentToolResponse.model_validate(raw)
    except ValidationError:
        return None


def parse_function_arguments(function: dict[str, object]) -> dict[str, object] | None:
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        return None
    try:
        data = json.loads(arguments)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def resolve_success_fields(
    *,
    tool_call_arguments: dict[str, object] | None,
    attachments: list[object],
) -> tuple[str, str, str]:
    """Return ``(display_url, title, mime_type)`` when rebuilding a success payload."""
    if tool_call_arguments is not None:
        attachment_url = tool_call_arguments.get("attachment_url")
        if isinstance(attachment_url, str) and attachment_url.strip():
            display_url = display_url_from_attachment_url(attachment_url)
            title = ""
            mime_type = ""
            for item in attachments:
                if not isinstance(item, dict):
                    continue
                item_url = item.get("url")
                if isinstance(item_url, str) and normalize_attachment_url_argument(
                    item_url
                ) == normalize_attachment_url_argument(display_url):
                    title = str(item.get("title") or title)
                    mime_type = str(item.get("type") or mime_type)
                    break
            if not title:
                title = display_url.rsplit("/", 1)[-1]
            return display_url, title, mime_type

    for item in attachments:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        display_url = normalize_attachment_url_argument(url)
        title = str(item.get("title") or display_url.rsplit("/", 1)[-1])
        mime_type = str(item.get("type") or "")
        return display_url, title, mime_type

    return "", "", ""
