from injector import inject

from quickapp.core.agent.models import OpenAiToolConfigDict


@inject
class _DeferredToolsContext:
    """Request-scoped holder for tool catalog and full definitions of deferred toolsets.

    Populated by toolset initializers (MCP, REST) for toolsets marked deferred=True.
    Read by AgentModule to filter schemas from the main LLM payload, and by
    _ToolSearchTool to serve the compact catalog and look up full definitions.
    """

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
