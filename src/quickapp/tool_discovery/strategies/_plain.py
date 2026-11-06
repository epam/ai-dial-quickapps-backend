from quickapp.config.tool_discovery import PlainSearchStrategyConfig
from quickapp.tool_discovery.routing_result import RoutingResult
from quickapp.tool_discovery.strategies._strategy import BaseStrategy


class PlainStrategy(BaseStrategy[PlainSearchStrategyConfig]):
    """One routing call over the whole catalog."""

    async def search(self, query: str) -> RoutingResult:
        return await self._route_tools(query, self._catalog)
