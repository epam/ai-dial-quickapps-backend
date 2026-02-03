import json
import mimetypes

from aidial_sdk.chat_completion import Message, Role

from quickapp.config.context import Context, FileContextConfig
from quickapp.config.tools.base import (
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.display.tool import ToolDisplayConfig, ToolStageConfig
from quickapp.config.tools.internal import InternalTool


def build_context_entries(
    contexts: list[Context],
    seen_urls: set[str],
) -> tuple[set[str], list[dict[str, str]]]:
    """Build context file metadata entries, flagging new ones.

    Returns (current_urls, entries) where current_urls is the set of URLs
    found in the current contexts and entries is the metadata list.
    """
    current_urls: set[str] = set()
    entries: list[dict[str, str]] = []

    for ctx in contexts:
        if not isinstance(ctx, FileContextConfig):
            continue
        url = ctx.url
        if url in current_urls:
            continue
        current_urls.add(url)
        title = url.rsplit("/", 1)[-1]
        mime_type = mimetypes.guess_type(title)[0] or ""
        entry: dict[str, str] = {
            "title": title,
            "url": url,
            "type": mime_type,
        }
        if ctx.description:
            entry["description"] = ctx.description
        if url not in seen_urls:
            entry["status"] = "new"
        entries.append(entry)

    for removed_url in seen_urls - current_urls:
        title = removed_url.rsplit("/", 1)[-1]
        entries.append({"title": title, "url": removed_url, "status": "removed"})

    return current_urls, entries


def extract_seen_urls_from_messages(messages: list[Message], tool_name: str) -> set[str]:
    """Scan message history for the most recent tool result from *tool_name*
    and extract the set of non-removed URLs that were previously reported."""
    context_call_ids: set[str] = set()
    for msg in messages:
        if msg.role == Role.ASSISTANT and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.function and tc.function.name == tool_name:
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
                    return {
                        entry["url"]
                        for entry in data
                        if isinstance(entry, dict)
                        and "url" in entry
                        and entry.get("status") != "removed"
                    }
            except (json.JSONDecodeError, KeyError):
                pass
    return set()


INTERNAL_TOOL_NAME_PREFIX = "quickapps_internal_"

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
