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
    expanded_folder_file_urls: set[str] | None = None,
    external_fetch_enabled: bool = False,
) -> bool:
    """True when the deployment accepts input attachments (``input_attachment_types``
    non-empty) **and** either external URL fetching is enabled (a url may then arrive
    via any channel, so it can't be predicted from request-visible files) or some
    request-visible file — admin context, expanded folder file, or user attachment —
    has an inferred MIME the deployment accepts.

    MIME inference is filename-based (matching ``build_context_entries_async``) and
    gated by :func:`quickapp.common.utils.matches_type`.
    """
    if not input_attachment_types:
        return False
    if external_fetch_enabled:
        return True
    for ctx in contexts:
        if not isinstance(ctx, FileContextConfig):
            continue
        mime = inferred_mime_type_for_file_context_url(ctx.url)
        if matches_type(mime, input_attachment_types):
            return True
    if expanded_folder_file_urls:
        for url in expanded_folder_file_urls:
            mime = inferred_mime_type_for_file_context_url(url)
            if matches_type(mime, input_attachment_types):
                return True
    for attachment in user_attachments_from_messages(messages):
        mime = attachment_mime_type(attachment)
        if matches_type(mime, input_attachment_types):
            return True
    return False
