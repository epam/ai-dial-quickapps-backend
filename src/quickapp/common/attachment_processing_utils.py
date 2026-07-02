"""Shared helpers for attachment URL/MIME handling (admin contexts + user attachments).

Used by attachment processing and agent pre-invocation transformers.
"""

import mimetypes
from collections.abc import Sequence

from aidial_sdk.chat_completion import Attachment, Message, Role


def inferred_mime_type_for_file_context_url(url: str) -> str:
    """Infer MIME from the filename segment of ``url``."""
    title = url.rsplit("/", 1)[-1]
    return mimetypes.guess_type(title)[0] or ""


def normalize_attachment_url_argument(raw: str) -> str:
    """Normalize a model-supplied attachment URL for comparison.

    Strips outer whitespace, then strips a single leading ``/`` so that
    DIAL-emitted forms ``/files/...`` and ``files/...`` compare equal. A
    leading ``//`` is preserved as-is (malformed; the ``files/`` prefix check
    then rejects it).
    """
    stripped = raw.strip()
    if stripped.startswith("/") and not stripped.startswith("//"):
        return stripped[1:]
    return stripped


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
