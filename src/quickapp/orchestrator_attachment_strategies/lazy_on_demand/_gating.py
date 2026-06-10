from collections.abc import Sequence

from aidial_sdk.chat_completion import Message

from quickapp.common.attachment_processing_utils import (
    attachment_mime_type,
    inferred_mime_type_for_file_context_url,
    user_attachments_from_messages,
)
from quickapp.common.utils import matches_type
from quickapp.config.context import Context, FileContextConfig


def should_enable_get_content_tool(
    contexts: Sequence[Context],
    messages: Sequence[Message],
    input_attachment_types: list[str] | None,
) -> bool:
    """True when some admin file context's or attachment in user message
    inferred MIME is allowed on the orchestrator path.

    Uses the same filename-based inference as ``build_context_entries`` in
    :mod:`quickapp.attachment_processing._context_entries` and DialCore
    ``input_attachment_types`` via :func:`quickapp.common.utils.matches_type`.
    Empty inferred MIME never matches unless the deployment patterns allow it.
    """
    for ctx in contexts:
        if not isinstance(ctx, FileContextConfig):
            continue
        mime = inferred_mime_type_for_file_context_url(ctx.url)
        if matches_type(mime, input_attachment_types):
            return True
    for attachment in user_attachments_from_messages(messages):
        mime = attachment_mime_type(attachment)
        if matches_type(mime, input_attachment_types):
            return True
    return False
