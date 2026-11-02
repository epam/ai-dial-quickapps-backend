from quickapp.common.deferred_tool_types import DeferredToolCatalogEntry, DeferredToolsetSummary
from quickapp.config.tool_discovery import PlainSearchStrategyConfig
from quickapp.tool_discovery._anonymous_agent import RoutingResult

from ._strategy import BaseStrategy


class PlainStrategy(BaseStrategy[PlainSearchStrategyConfig]):
    """One routing call over the whole catalog."""

    async def search(
        self,
        query: str,
        catalog: list[DeferredToolCatalogEntry],
        toolset_summaries: list[DeferredToolsetSummary],
    ) -> RoutingResult:
        del toolset_summaries  # unused by this strategy
        return await self._route_tools(query, catalog)
