import json
import mimetypes
from collections.abc import Sequence
from enum import Enum

from aidial_sdk.chat_completion import Message, Role
from pydantic import BaseModel, ValidationError

from quickapp.config.context import Context, FileContextConfig
from quickapp.internal_tooling.attachment_notification_tooling._tool_configs import (
    AVAILABLE_CONTEXT_TOOL_NAME,
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


def _parse_context_entries(content: str) -> dict[str, ContextEntry] | None:
    """Parse a JSON tool result into a URL → ContextEntry mapping.

    Returns None if the content is not a valid context-tool result.
    """
    try:
        data = json.loads(content)
        if not isinstance(data, list):
            return None
        result: dict[str, ContextEntry] = {}
        for raw in data:
            if isinstance(raw, dict) and "url" in raw:
                entry = ContextEntry.model_validate(raw)
                if entry.status != ContextEntryStatus.removed:
                    result[entry.url] = entry
        return result
    except (json.JSONDecodeError, KeyError, ValidationError):
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
                    and tc.function.name == AVAILABLE_CONTEXT_TOOL_NAME
                    and tc.id in tool_contents
                ):
                    result = _parse_context_entries(tool_contents[tc.id])
                    if result is not None:
                        return result
    return {}


def has_context_tool_history(messages: Sequence[Message]) -> bool:
    """Check whether message history contains any tool calls for the context tool."""
    for msg in messages:
        if msg.role == Role.ASSISTANT and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.function and tc.function.name == AVAILABLE_CONTEXT_TOOL_NAME:
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
