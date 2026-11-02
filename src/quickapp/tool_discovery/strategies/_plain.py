from quickapp.common.deferred_tool_types import DeferredToolCatalogEntry, DeferredToolsetSummary
from quickapp.config.tool_discovery import PlainSearchStrategy
from quickapp.tool_discovery._anonymous_agent import _AnonymousAgent, _RoutingResult


class PlainStrategy:
    """One routing call over the whole catalog."""

    def __init__(self, agent: _AnonymousAgent, settings: PlainSearchStrategy) -> None:
        self.__agent = agent
        self.__settings = settings

    async def search(
        self,
        query: str,
        catalog: list[DeferredToolCatalogEntry],
        toolset_summaries: list[DeferredToolsetSummary],
    ) -> _RoutingResult:
        return await self.__agent.route(
            query,
            catalog,
            kind="tool",
            limit=self.__settings.top_k,
            threshold=self.__settings.score_threshold,
        )
