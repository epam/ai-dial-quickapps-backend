from typing import Protocol

from quickapp.common.deferred_tool_types import DeferredToolCatalogEntry
from quickapp.common.deployment_usage import ModelUsage
from quickapp.config.tool_discovery import BaseSearchStrategyConfig
from quickapp.tool_discovery._anonymous_agent import _AnonymousAgent
from quickapp.tool_discovery.routing_result import RoutingResult


class ToolSearchStrategy(Protocol):
    async def search(self, query: str) -> RoutingResult:
        """Return the catalog tools that best match the query (best first) and the routing usage."""
        ...


def sum_routing_usage(*results: RoutingResult) -> ModelUsage | None:
    """Total the usage of several routing calls (all made against the same model)."""
    usages = [r.usage for r in results if r.usage is not None]
    if not usages:
        return None
    return ModelUsage(
        model=usages[0].model,
        prompt_tokens=sum(u.prompt_tokens for u in usages),
        completion_tokens=sum(u.completion_tokens for u in usages),
    )


class BaseStrategy[ConfigT: BaseSearchStrategyConfig]:
    """Holds the routing agent, the strategy config and the request's deferred catalog."""

    def __init__(
        self,
        agent: _AnonymousAgent,
        config: ConfigT,
        catalog: list[DeferredToolCatalogEntry],
    ) -> None:
        self._agent = agent
        self._config = config
        self._catalog = catalog

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
