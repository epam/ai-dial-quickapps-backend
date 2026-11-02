from typing import Protocol

from quickapp.common.deferred_tool_types import DeferredToolCatalogEntry, DeferredToolsetSummary
from quickapp.tool_discovery._anonymous_agent import _RoutingResult


class ToolSearchStrategy(Protocol):
    async def search(
        self,
        query: str,
        catalog: list[DeferredToolCatalogEntry],
        toolset_summaries: list[DeferredToolsetSummary],
    ) -> _RoutingResult:
        """Return the catalog tools that best match the query (best first) and the routing usage."""
        ...
