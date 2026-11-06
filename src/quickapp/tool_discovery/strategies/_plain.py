from quickapp.config.tool_discovery import PlainSearchStrategyConfig

from .._routing_result import RoutingResult
from ._strategy import ToolSearchStrategy


class PlainStrategy(ToolSearchStrategy[PlainSearchStrategyConfig]):
    """One routing call over the whole catalog."""

    async def search(self, query: str) -> RoutingResult:
        return await self._route_tools(query, self._catalog)
