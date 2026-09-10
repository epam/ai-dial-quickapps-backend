from injector import inject

from quickapp.common import StagedBaseTool
from quickapp.config.tools.base import BaseOpenAITool
from quickapp.core.agent.models import OpenAiToolConfigDict


@inject
class _DeferredToolsContext:
    """Request-scoped holder for tool catalog and full definitions of deferred toolsets."""

    def __init__(self) -> None:
        self._catalog: list[dict[str, str]] = []
        self._definitions: dict[str, OpenAiToolConfigDict] = {}

    def register_deferred_tools(
        self,
        catalog_entries: list[dict[str, str]],
        definitions: dict[str, OpenAiToolConfigDict],
    ) -> None:
        self._catalog.extend(catalog_entries)
        self._definitions.update(definitions)

    @property
    def deferred_names(self) -> frozenset[str]:
        return frozenset(self._definitions.keys())

    @property
    def catalog(self) -> list[dict[str, str]]:
        return list(self._catalog)

    def get_definition(self, name: str) -> OpenAiToolConfigDict | None:
        return self._definitions.get(name)


def register_tools_as_deferred(
    tools: list[StagedBaseTool],
    context: _DeferredToolsContext,
) -> None:
    """Build catalog + definitions from tools and register them as deferred."""
    entries: list[tuple[StagedBaseTool, str]] = [
        (t, name)
        for t in tools
        if isinstance(t.tool_config, BaseOpenAITool)
        and (name := t.tool_config.open_ai_tool.function.name)
    ]
    catalog: list[dict[str, str]] = [
        {
            "name": name,
            "description": t.tool_config.open_ai_tool.function.description or "",  # type: ignore[union-attr]
        }
        for t, name in entries
    ]
    definitions: dict[str, OpenAiToolConfigDict] = {
        name: t.tool_config.open_ai_tool.model_dump(mode="json", exclude_none=True)  # type: ignore[union-attr]
        for t, name in entries
    }
    context.register_deferred_tools(catalog, definitions)
