import logging

from quickapp.common.deferred_tool_types import DeferredToolCatalogEntry, DeferredToolsetSummary
from quickapp.config.tool_discovery import HierarchySearchStrategyConfig
from quickapp.tool_discovery._anonymous_agent import _AnonymousAgent
from quickapp.tool_discovery.routing_result import RoutingResult
from quickapp.tool_discovery.strategies._strategy import BaseStrategy, sum_routing_usage

logger = logging.getLogger(__name__)


class HierarchyStrategy(BaseStrategy[HierarchySearchStrategyConfig]):
    """Picks toolsets first, then tools among the tools of the chosen toolsets.

    Tools are joined to their toolset by the localized toolset display name, so two toolsets
    sharing a display name are treated as one: choosing either pulls in the tools of both.
    """

    def __init__(
        self,
        agent: _AnonymousAgent,
        config: HierarchySearchStrategyConfig,
        catalog: list[DeferredToolCatalogEntry],
        toolset_summaries: list[DeferredToolsetSummary],
    ) -> None:
        super().__init__(agent, config, catalog)
        self._toolset_summaries = toolset_summaries

    async def search(self, query: str) -> RoutingResult:
        candidates, stage_one = await self._pick_candidates(query)
        picked = await self._route_tools(query, candidates)
        return picked.with_usage(sum_routing_usage(stage_one, picked))

    async def _pick_candidates(
        self, query: str
    ) -> tuple[list[DeferredToolCatalogEntry], RoutingResult]:
        """Stage 1: narrow the catalog to the tools of the chosen toolsets."""
        if len(self._toolset_summaries) <= 1:
            return self._catalog, RoutingResult()

        stage_one = await self._agent.route(
            query,
            self._toolset_summaries,
            kind="toolset",
            limit=self._config.toolset_top_k,
            threshold=self._config.score_threshold,
        )
        chosen = set(stage_one.names)
        scoped = [entry for entry in self._catalog if entry["toolset"] in chosen]
        if scoped:
            return scoped, stage_one
        logger.info("Hierarchy stage 1 found no toolset, searching the whole catalog")
        return self._catalog, stage_one
