import logging

from quickapp.common.deferred_tool_types import DeferredToolCatalogEntry, DeferredToolsetSummary
from quickapp.config.tool_discovery import HierarchySearchStrategyConfig
from quickapp.tool_discovery._anonymous_agent import RoutingResult

from ._strategy import BaseStrategy, sum_routing_usage

logger = logging.getLogger(__name__)


class HierarchyStrategy(BaseStrategy[HierarchySearchStrategyConfig]):
    """Picks toolsets first, then tools among the tools of the chosen toolsets."""

    async def search(
        self,
        query: str,
        catalog: list[DeferredToolCatalogEntry],
        toolset_summaries: list[DeferredToolsetSummary],
    ) -> RoutingResult:
        candidates = catalog
        stage_one = RoutingResult()

        if len(toolset_summaries) > 1:
            stage_one = await self._agent.route(
                query,
                toolset_summaries,
                kind="toolset",
                limit=self._config.toolset_top_k,
                threshold=self._config.score_threshold,
            )
            chosen = set(stage_one.names)
            scoped = [entry for entry in catalog if entry["toolset"] in chosen]
            if scoped:
                candidates = scoped
            else:
                logger.info("Hierarchy stage 1 found no toolset, searching the whole catalog")

        picked = await self._route_tools(query, candidates)
        return picked.with_usage(sum_routing_usage(stage_one, picked))
