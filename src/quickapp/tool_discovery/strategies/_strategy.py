from abc import ABC, abstractmethod

from quickapp.common.deferred_tool_types import DeferredToolCatalogEntry
from quickapp.config.tool_discovery import BaseSearchStrategyConfig

from .._anonymous_agent import _AnonymousAgent
from .._routing_result import RoutingResult


class ToolSearchStrategy[ConfigT: BaseSearchStrategyConfig](ABC):
    """Finds the best matching tools of the request's deferred catalog.

    Holds the routing agent, the strategy config and the catalog; concrete strategies decide
    how many routing calls are made and over which part of the catalog.
    """

    def __init__(
        self,
        agent: _AnonymousAgent,
        config: ConfigT,
        catalog: list[DeferredToolCatalogEntry],
    ) -> None:
        self._agent = agent
        self._config = config
        self._catalog = catalog

    @abstractmethod
    async def search(self, query: str) -> RoutingResult:
        """Return the catalog tools that best match the query (best first) and the routing usage."""

    async def _route_tools(
        self,
        query: str,
        entries: list[DeferredToolCatalogEntry],
        *,
        limit: int | None = None,
    ) -> RoutingResult:
        return await self._agent.route(
            query,
            entries,
            kind="tool",
            limit=self._config.top_k if limit is None else limit,
            threshold=self._config.score_threshold,
        )
