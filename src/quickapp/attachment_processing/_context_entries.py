import mimetypes
from collections.abc import Sequence
from enum import Enum

from aidial_sdk.chat_completion import Message, Role
from pydantic import BaseModel, Field, ValidationError

from quickapp.common.attachment_processing_utils import (
    attachment_mime_type,
    inferred_mime_type_for_file_context_url,
    user_attachments_from_messages,
)
from quickapp.common.tool_names import (
    INTERNAL_ATTACHMENTS_AVAILABLE_CONTEXT_TOOL_NAME,
    INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
)
from quickapp.common.utils import matches_type
from quickapp.config.context import Context, FileContextConfig

context_tool_names = frozenset(
    {
        INTERNAL_ATTACHMENTS_AVAILABLE_CONTEXT_TOOL_NAME,
        INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
    }
)


class ContextEntryStatus(str, Enum):
    new = "new"
    removed = "removed"
    updated = "updated"


class ContextEntry(BaseModel):
    title: str
    url: str
    type: str = ""
    description: str | None = None
    status: ContextEntryStatus | None = None


class AvailableContextToolResponse(BaseModel):
    entries: list[ContextEntry] = Field()
    disclaimer: str = Field(
        default=(
            "This information is related only to the files configured by admin. It does not contain any information "
            "on attachments from user or from tool results. "
            "To load a user attachment, use internal_attachments_get_content with exact url from <attachments>."
        )
    )


def build_context_entries(
    contexts: list[Context],
    seen_entries: dict[str, ContextEntry],
) -> tuple[set[str], list[ContextEntry]]:
    """Build context file metadata entries, flagging new ones.

    Returns (current_urls, entries) where current_urls is the set of URLs
    found in the current contexts and entries is the metadata list.
    """
    current_urls: set[str] = set()
    entries: list[ContextEntry] = []

    for ctx in contexts:
        if not isinstance(ctx, FileContextConfig):
            continue
        url = ctx.url
        if url in current_urls:
            continue
        current_urls.add(url)
        title = url.rsplit("/", 1)[-1]
        mime_type = mimetypes.guess_type(title)[0] or ""
        if url not in seen_entries:
            status = ContextEntryStatus.new
        else:
            prev = seen_entries[url]
            if prev.description != (ctx.description or None) or prev.type != mime_type:
                status = ContextEntryStatus.updated
            else:
                status = None

        entries.append(
            ContextEntry(
                title=title,
                url=url,
                type=mime_type,
                description=ctx.description or None,
                status=status,
            )
        )

    for removed_url in set(seen_entries) - current_urls:
        prev = seen_entries[removed_url]
        entries.append(
            ContextEntry(
                title=prev.title,
                url=prev.url,
                type=prev.type,
                description=prev.description,
                status=ContextEntryStatus.removed,
            )
        )

    return current_urls, entries


def should_enable_get_content_tool(
    contexts: Sequence[Context],
    messages: Sequence[Message],
    input_attachment_types: list[str] | None,
) -> bool:
    """True when some admin file context's or attachment in user message inferred MIME is allowed on the orchestrator path.

    Uses the same filename-based inference as :func:`build_context_entries` and DialCore
    ``input_attachment_types`` via :func:`quickapp.common.utils.matches_type`. Empty inferred
    MIME never matches unless the deployment patterns allow it.
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


def _parse_tool_response(content: str) -> dict[str, ContextEntry] | None:
    """Parse a JSON tool response into a URL → ContextEntry mapping, ignoring removed entries.

    Returns None if the content is not a valid context-tool response.
    """
    try:
        response = AvailableContextToolResponse.model_validate_json(content)
        result: dict[str, ContextEntry] = {}
        for entry in response.entries:
            if entry.status != ContextEntryStatus.removed:
                result[entry.url] = entry
        return result
    except ValidationError:
        return None


def extract_seen_entries_from_messages(messages: list[Message]) -> dict[str, ContextEntry]:
    """Scan message history for the most recent context-tool result
    and extract a mapping of URL → ContextEntry for non-removed entries."""
    # Single reverse pass: TOOL results appear after their ASSISTANT message
    # in forward order, so in reverse we see TOOL messages first.
    tool_contents: dict[str, str] = {}
    for msg in reversed(messages):
        if msg.role == Role.TOOL and msg.tool_call_id and msg.content:
            tool_contents[msg.tool_call_id] = str(msg.content)
        elif msg.role == Role.ASSISTANT and msg.tool_calls:
            for tc in msg.tool_calls:
                if (
                    tc.function
                    and tc.function.name == INTERNAL_ATTACHMENTS_AVAILABLE_CONTEXT_TOOL_NAME
                    and tc.id in tool_contents
                ):
                    result = _parse_tool_response(tool_contents[tc.id])
                    if result is not None:
                        return result
    return {}


def has_context_tool_history(messages: Sequence[Message]) -> bool:
    """Check whether message history contains any tool calls for the context list or fetch tools."""
    for msg in messages:
        if msg.role == Role.ASSISTANT and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.function and tc.function.name in context_tool_names:
                    return True
    return False


def should_activate_context_tool(
    contexts: Sequence[Context],
    messages: Sequence[Message],
) -> bool:
    """True when file contexts exist OR the context tool was used in a prior turn."""
    if any(isinstance(ctx, FileContextConfig) for ctx in contexts):
        return True
    return has_context_tool_history(messages)
