"""Structured payloads for ``internal_attachments_get_content`` TOOL messages.

Human-readable summaries live in ``content``; canonical structured data lives in
``custom_content.state[GET_CONTENT_RESPONSE_STATE_KEY]``.
"""

import json
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, ValidationError

from quickapp.common.attachment_processing_utils import normalize_attachment_url_argument
from quickapp.common.file_reference_pattern import FILE_PATTERN, to_file_url_reference
from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME

GET_CONTENT_RESPONSE_STATE_KEY = "_get_content_response"

HISTORY_ATTACHMENT_REMOVED_STATUS_MESSAGE = (
    "The file attachment payload was removed from saved history to save context. "
    f"Call {INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME} again with attachment_url "
    "when you need the content. Do not ask the user to re-upload."
)


class GetContentStatus(StrEnum):
    SUCCESS = "Success"
    FAIL = "Fail"


class GetContentToolResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: GetContentStatus
    attachment_url: str | None = None
    title: str | None = None
    type: str | None = None
    status_message: str | None = None
    accepted_types: list[str] | None = None

    @classmethod
    def success(cls, *, display_url: str, title: str, mime_type: str) -> Self:
        return cls(
            status=GetContentStatus.SUCCESS,
            attachment_url=_model_facing_attachment_url(display_url),
            title=title,
            type=mime_type,
        )

    @classmethod
    def for_history(cls, *, display_url: str, title: str, mime_type: str) -> Self:
        return cls.success(
            display_url=display_url,
            title=title,
            mime_type=mime_type,
        ).model_copy(update={"status_message": HISTORY_ATTACHMENT_REMOVED_STATUS_MESSAGE})

    @classmethod
    def fail(cls, *, message: str, accepted_types: list[str]) -> Self:
        return cls(
            status=GetContentStatus.FAIL,
            status_message=message,
            accepted_types=accepted_types,
        )

    @classmethod
    def from_state(cls, state: object) -> Self | None:
        if not isinstance(state, dict):
            return None
        raw = state.get(GET_CONTENT_RESPONSE_STATE_KEY)
        if raw is None:
            return None
        try:
            return cls.model_validate(raw)
        except ValidationError:
            return None

    def to_state_entry(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude_none=True)

    def content_summary(self) -> str:
        if self.status == GetContentStatus.FAIL:
            parts = [f"Failed to load attachment: {self.status_message or 'Unknown error'}."]
            if self.accepted_types:
                parts.append(f"Accepted MIME types: {', '.join(self.accepted_types)}.")
            return " ".join(parts)

        title = self.title or "file"
        mime = self.type or "application/octet-stream"
        url = self.attachment_url or ""
        lines = [f'Loaded file "{title}" ({mime}) from {url}.']
        if self.status_message:
            lines.append(self.status_message)
        return "\n".join(lines)

    def tool_parts(self) -> tuple[str, dict[str, object]]:
        return self.content_summary(), {GET_CONTENT_RESPONSE_STATE_KEY: self.to_state_entry()}

    def merge_into_state(self, existing: dict[str, object] | None) -> dict[str, object]:
        merged = dict(existing or {})
        merged[GET_CONTENT_RESPONSE_STATE_KEY] = self.to_state_entry()
        return merged


def _model_facing_attachment_url(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if FILE_PATTERN.match(value):
        return value
    return to_file_url_reference(normalize_attachment_url_argument(value))


def _display_url_from_attachment_url(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    match = FILE_PATTERN.match(value)
    if match:
        bare = match.group("file_url") or ""
        return normalize_attachment_url_argument(bare) if bare else ""
    return normalize_attachment_url_argument(value)


def _resolve_success_fields(
    *,
    tool_call_arguments: dict[str, object] | None,
    attachments: list[object],
) -> tuple[str, str, str]:
    if tool_call_arguments is not None:
        attachment_url = tool_call_arguments.get("attachment_url")
        if isinstance(attachment_url, str) and attachment_url.strip():
            display_url = _display_url_from_attachment_url(attachment_url)
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


def parse_function_arguments(function: dict[str, object]) -> dict[str, object] | None:
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        return None
    try:
        data = json.loads(arguments)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def history_strip_response(
    *,
    tool_call_arguments: dict[str, object] | None,
    attachments: list[object],
    state: dict[str, object] | None,
) -> GetContentToolResponse:
    """Build the post-strip success payload for persisted get-content history."""
    state_dict = state or {}
    attachment_url = (
        tool_call_arguments.get("attachment_url") if tool_call_arguments is not None else None
    )
    if isinstance(attachment_url, str) and attachment_url.strip():
        display_url, title, mime_type = _resolve_success_fields(
            tool_call_arguments=tool_call_arguments,
            attachments=attachments,
        )
    else:
        existing = GetContentToolResponse.from_state(state_dict)
        if existing is not None and existing.status == GetContentStatus.SUCCESS:
            display_url = _display_url_from_attachment_url(existing.attachment_url or "")
            title = existing.title or ""
            mime_type = existing.type or ""
        else:
            display_url, title, mime_type = _resolve_success_fields(
                tool_call_arguments=None,
                attachments=attachments,
            )
    return GetContentToolResponse.for_history(
        display_url=display_url,
        title=title,
        mime_type=mime_type,
    )
