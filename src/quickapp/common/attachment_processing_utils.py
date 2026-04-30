"""Shared helpers for attachment URL allowlists (admin contexts + user attachments).

Used by attachment processing and agent pre-invocation transformers.
"""

from __future__ import annotations

import mimetypes
from collections.abc import Sequence

from aidial_sdk.chat_completion import Attachment, Message, Role

from quickapp.common.utils import matches_type
from quickapp.config.context import Context, FileContextConfig


def inferred_mime_type_for_file_context_url(url: str) -> str:
    """Infer MIME from the filename segment of ``url``."""
    title = url.rsplit("/", 1)[-1]
    return mimetypes.guess_type(title)[0] or ""


def normalize_attachment_url_argument(raw: str) -> str:
    """Normalize a model-supplied attachment URL for whitelist comparison: strip outer whitespace only."""
    return raw.strip()


def normalize_context_url_argument(raw: str) -> str:
    """Backward-compatible alias for older call sites."""
    return normalize_attachment_url_argument(raw)


def user_attachments_from_messages(messages: Sequence[Message]) -> list[Attachment]:
    """Extract all attachments from user-role messages in chronological order."""
    attachments: list[Attachment] = []
    for message in messages:
        if message.role != Role.USER or not message.custom_content:
            continue
        raw = message.custom_content.attachments
        if raw:
            attachments.extend(raw)
    return attachments


def attachment_mime_type(attachment: Attachment) -> str:
    """Resolve attachment MIME from explicit type first, then from URL filename."""
    if attachment.type:
        return attachment.type
    if attachment.url:
        return inferred_mime_type_for_file_context_url(attachment.url)
    return ""


def collect_get_content_allowed_urls(
    contexts: Sequence[Context],
    messages: Sequence[Message],
    input_attachment_types: list[str] | None,
) -> set[str]:
    """Collect normalized URLs get-content is allowed to fetch.

    Allowed set combines:
    - admin file contexts accepted by the orchestrator
    - user message attachments accepted by the orchestrator
    """
    allowed_urls: set[str] = set()
    for ctx in contexts:
        if not isinstance(ctx, FileContextConfig):
            continue
        mime = inferred_mime_type_for_file_context_url(ctx.url)
        if matches_type(mime, input_attachment_types):
            allowed_urls.add(normalize_attachment_url_argument(ctx.url))

    for attachment in user_attachments_from_messages(messages):
        if not attachment.url:
            continue
        mime = attachment_mime_type(attachment)
        if matches_type(mime, input_attachment_types):
            allowed_urls.add(normalize_attachment_url_argument(str(attachment.url)))

    return allowed_urls
