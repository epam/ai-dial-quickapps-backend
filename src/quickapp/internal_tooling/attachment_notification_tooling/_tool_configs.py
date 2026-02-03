import mimetypes

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
