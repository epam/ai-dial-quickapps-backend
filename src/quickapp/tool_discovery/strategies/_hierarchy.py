import logging

from quickapp.common.deferred_tool_types import DeferredToolCatalogEntry, DeferredToolsetSummary
from quickapp.config.tool_discovery import HierarchySearchStrategy
from quickapp.tool_discovery._anonymous_agent import (
    _AnonymousAgent,
    _RoutingResult,
    sum_routing_usage,
)

logger = logging.getLogger(__name__)


class HierarchyStrategy:
    """Picks toolsets first, then tools among the tools of the chosen toolsets."""

    def __init__(self, agent: _AnonymousAgent, settings: HierarchySearchStrategy) -> None:
        self.__agent = agent
        self.__settings = settings

    async def search(
        self,
        query: str,
        catalog: list[DeferredToolCatalogEntry],
        toolset_summaries: list[DeferredToolsetSummary],
    ) -> _RoutingResult:
        settings = self.__settings
        candidates: list[DeferredToolCatalogEntry] = catalog
        stage_one = _RoutingResult()

        if len(toolset_summaries) > 1:
            stage_one = await self.__agent.route(
                query,
                toolset_summaries,
                kind="toolset",
                limit=settings.toolset_top_k,
                threshold=settings.score_threshold,
            )
            chosen = set(stage_one.names)
            scoped = [entry for entry in catalog if entry.get("toolset") in chosen]
            if scoped:
                candidates = scoped
            else:
                logger.info("Hierarchy stage 1 found no toolset, searching the whole catalog")

        picked = await self.__agent.route(
            query,
            candidates,
            kind="tool",
            limit=settings.top_k,
            threshold=settings.score_threshold,
        )
        return picked.with_usage(sum_routing_usage(stage_one, picked))
