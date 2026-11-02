from typing import Protocol

from quickapp.common.deferred_tool_types import DeferredToolCatalogEntry, DeferredToolsetSummary
from quickapp.common.deployment_usage import ModelUsage
from quickapp.config.tool_discovery import BaseSearchStrategyConfig
from quickapp.tool_discovery._anonymous_agent import RoutingResult, _AnonymousAgent


class ToolSearchStrategy(Protocol):
    async def search(
        self,
        query: str,
        catalog: list[DeferredToolCatalogEntry],
        toolset_summaries: list[DeferredToolsetSummary],
    ) -> RoutingResult:
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
    """Holds the routing agent and the strategy config, and runs the shared plain routing call."""

    def __init__(self, agent: _AnonymousAgent, config: ConfigT) -> None:
        self._agent = agent
        self._config = config

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
            limit=limit or self._config.top_k,
            threshold=self._config.score_threshold,
        )
