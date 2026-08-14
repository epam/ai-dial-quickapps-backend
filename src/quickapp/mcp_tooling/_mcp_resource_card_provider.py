from injector import inject

from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.mcp_tooling._mcp_tooling_context import _MCPToolingContext


@inject
class _MCPResourceCardProvider(PromptPartProvider):
    """Renders a frontmatter card for each listed MCP resource into the system prompt.

    Cards list resource name, URI, optional MIME type, and description so the LLM
    knows what is available without bearing the token cost of content upfront.
    The LLM fetches content on demand via the ``read_mcp_resource`` tool.
    """

    def __init__(self, context: _MCPToolingContext) -> None:
        self._context = context

    async def get_prompt_part(self) -> str:
        metas = self._context.resource_metas
        if not metas:
            return ""

        parts: list[str] = []
        for meta in metas:
            lines: list[str] = [
                f"--- Resource: {meta.resource_name} ({meta.toolset_name}) ---",
                f"URI: {meta.resource_uri}",
            ]
            if meta.mime_type:
                lines.append(f"MIME type: {meta.mime_type}")
            description = meta.resource_description or meta.toolset_description
            if description:
                lines.append(description)
            parts.append("\n".join(lines))

        return "\n\n".join(parts)
