import mimetypes
from collections.abc import Sequence
from enum import Enum

from aidial_sdk.chat_completion import Message, Role
from pydantic import BaseModel, Field, ValidationError

from quickapp.attachment_processing._expanded_context_file_urls import ExpandedContextFileUrls
from quickapp.common.abstract.folder_listing_provider import (
    ExpandedFolderEntry,
    FolderListingProvider,
)
from quickapp.common.folder_context_urls import (
    FOLDER_METADATA_MIME,
    metadata_folder_url_to_files_url,
)
from quickapp.common.tool_names import (
    INTERNAL_ATTACHMENTS_AVAILABLE_CONTEXT_TOOL_NAME,
    INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
)
from quickapp.common.utils import posix_path_last_segment
from quickapp.config.context import Context, FileContextConfig, FolderContextConfig

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
            "on attachments from user or from tool results."
        )
    )


def _append_context_entry(
    *,
    url: str,
    mime_type: str,
    description: str | None,
    seen_entries: dict[str, ContextEntry],
    current_urls: set[str],
    entries: list[ContextEntry],
) -> None:
    if url in current_urls:
        return
    current_urls.add(url)
    title = posix_path_last_segment(url.rstrip("/")) or url
    if url not in seen_entries:
        status = ContextEntryStatus.new
    else:
        prev = seen_entries[url]
        if prev.description != description or prev.type != mime_type:
            status = ContextEntryStatus.updated
        else:
            status = None

    entries.append(
        ContextEntry(
            title=title,
            url=url,
            type=mime_type,
            description=description,
            status=status,
        )
    )


async def _list_folder_children(
    files_url: str,
    *,
    max_depth: int,
    folder_listing: FolderListingProvider,
    cache: ExpandedContextFileUrls,
) -> list[ExpandedFolderEntry]:
    key = (files_url, max_depth)
    cached = cache.folder_children.get(key)
    if cached is not None:
        return cached
    children = await folder_listing.list_folder_entries(files_url, max_depth=max_depth)
    cache.folder_children[key] = children
    return children


async def _expand_folder_context(
    ctx: FolderContextConfig,
    *,
    folder_listing: FolderListingProvider,
    seen_entries: dict[str, ContextEntry],
    current_urls: set[str],
    entries: list[ContextEntry],
    expanded_file_urls: set[str],
    folder_listing_cache: ExpandedContextFileUrls,
) -> None:
    _append_context_entry(
        url=ctx.url,
        mime_type=ctx.mime,
        description=ctx.description or None,
        seen_entries=seen_entries,
        current_urls=current_urls,
        entries=entries,
    )

    files_url = metadata_folder_url_to_files_url(ctx.url)
    children = await _list_folder_children(
        files_url,
        max_depth=ctx.max_depth,
        folder_listing=folder_listing,
        cache=folder_listing_cache,
    )
    for child in children:
        if child.is_folder:
            mime_type = FOLDER_METADATA_MIME
            description = None
        else:
            title = posix_path_last_segment(child.url)
            mime_type = mimetypes.guess_type(title)[0] or ""
            description = None
            expanded_file_urls.add(child.url)
        _append_context_entry(
            url=child.url,
            mime_type=mime_type,
            description=description,
            seen_entries=seen_entries,
            current_urls=current_urls,
            entries=entries,
        )


async def build_context_entries_async(
    contexts: list[Context],
    seen_entries: dict[str, ContextEntry],
    folder_listing: FolderListingProvider,
    expanded_file_urls_holder: ExpandedContextFileUrls,
) -> tuple[set[str], list[ContextEntry]]:
    """Build context metadata entries, expanding folder contexts recursively."""
    current_urls: set[str] = set()
    entries: list[ContextEntry] = []
    expanded_file_urls: set[str] = set()

    for ctx in contexts:
        if isinstance(ctx, FileContextConfig):
            mime_type = mimetypes.guess_type(posix_path_last_segment(ctx.url))[0] or ""
            _append_context_entry(
                url=ctx.url,
                mime_type=mime_type,
                description=ctx.description or None,
                seen_entries=seen_entries,
                current_urls=current_urls,
                entries=entries,
            )
        elif isinstance(ctx, FolderContextConfig):
            await _expand_folder_context(
                ctx,
                folder_listing=folder_listing,
                seen_entries=seen_entries,
                current_urls=current_urls,
                entries=entries,
                expanded_file_urls=expanded_file_urls,
                folder_listing_cache=expanded_file_urls_holder,
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

    expanded_file_urls_holder.urls = expanded_file_urls
    expanded_file_urls_holder.populated = True

    return current_urls, entries


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
    """True when file or folder contexts exist OR the context tool was used in a prior turn."""
    if any(isinstance(ctx, (FileContextConfig, FolderContextConfig)) for ctx in contexts):
        return True
    return has_context_tool_history(messages)
