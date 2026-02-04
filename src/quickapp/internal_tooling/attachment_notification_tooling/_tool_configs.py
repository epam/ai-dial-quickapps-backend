import json
import mimetypes
from collections.abc import Sequence
from enum import Enum

from aidial_sdk.chat_completion import Message, Role
from pydantic import BaseModel, ValidationError

from quickapp.config.context import Context, FileContextConfig
from quickapp.config.tools.base import (
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.display.tool import ToolDisplayConfig, ToolStageConfig
from quickapp.config.tools.internal import InternalTool

INTERNAL_TOOL_NAME_PREFIX = "quickapps_internal_"


class ContextEntryStatus(str, Enum):
    new = "new"
    removed = "removed"


class ContextEntry(BaseModel):
    title: str
    url: str
    type: str = ""
    description: str | None = None
    status: ContextEntryStatus | None = None


AVAILABLE_CONTEXT_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=f"{INTERNAL_TOOL_NAME_PREFIX}available_context",
            description=(
                "Returns metadata about admin-configured context files"
                " attached to this application."
            ),
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={},
            ),
        )
    ),
    display=ToolDisplayConfig(stage=ToolStageConfig(name="Available context")),
)

# Tool name after hashing by OpenAiToolFunction.set_name validator
AVAILABLE_CONTEXT_TOOL_NAME = AVAILABLE_CONTEXT_TOOL_CONFIG.open_ai_tool.function.name


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
        entries.append(
            ContextEntry(
                title=title,
                url=url,
                type=mime_type,
                description=ctx.description or None,
                status=ContextEntryStatus.new if url not in seen_entries else None,
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


def extract_seen_entries_from_messages(messages: list[Message]) -> dict[str, ContextEntry]:
    """Scan message history for the most recent context-tool result
    and extract a mapping of URL → ContextEntry for non-removed entries."""
    context_call_ids: set[str] = set()
    for msg in messages:
        if msg.role == Role.ASSISTANT and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.function and tc.function.name == AVAILABLE_CONTEXT_TOOL_NAME:
                    context_call_ids.add(tc.id)

    # Walk in reverse to find the most recent matching tool result
    for msg in reversed(messages):
        if (
            msg.role == Role.TOOL
            and msg.tool_call_id
            and msg.tool_call_id in context_call_ids
            and msg.content
        ):
            try:
                data = json.loads(str(msg.content))
                if isinstance(data, list):
                    result: dict[str, ContextEntry] = {}
                    for raw in data:
                        if isinstance(raw, dict) and "url" in raw:
                            entry = ContextEntry.model_validate(raw)
                            if entry.status != ContextEntryStatus.removed:
                                result[entry.url] = entry
                    return result
            except (json.JSONDecodeError, KeyError, ValidationError):
                pass
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
