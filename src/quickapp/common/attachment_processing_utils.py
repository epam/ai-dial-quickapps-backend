"""Shared helpers for attachment URL/MIME handling (admin contexts + user attachments).

Used by attachment processing and agent pre-invocation transformers.
"""

import mimetypes
from collections.abc import Mapping, Sequence
from xml.sax.saxutils import escape

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


def _attachment_field(
    attachment: Attachment | Mapping[str, object],
    field: str,
) -> str:
    if isinstance(attachment, Mapping):
        value = attachment.get(field)
        return "" if value is None else str(value)
    return "" if getattr(attachment, field, None) is None else str(getattr(attachment, field))


def build_attachment_xml_metadata(
    attachments: Sequence[Attachment | Mapping[str, object]],
) -> str:
    """Serialize attachment title/type/url metadata as XML for model-facing text."""
    xml_parts = ["<attachments>"]
    for attachment in attachments:
        xml_parts.append("  <attachment>")
        xml_parts.append(f"    <title>{escape(_attachment_field(attachment, 'title'))}</title>")
        xml_parts.append(f"    <type>{escape(_attachment_field(attachment, 'type'))}</type>")
        xml_parts.append(f"    <url>{escape(_attachment_field(attachment, 'url'))}</url>")
        reference_url = (
            attachment.get("reference_url")
            if isinstance(attachment, Mapping)
            else attachment.reference_url
        )
        if reference_url is not None:
            xml_parts.append(f"    <reference_url>{escape(str(reference_url))}</reference_url>")
        xml_parts.append("  </attachment>")
    xml_parts.append("</attachments>")
    return "\n".join(xml_parts)
