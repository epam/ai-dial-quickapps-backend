import asyncio

from quickapp.common.deferred_tool_types import DeferredToolCatalogEntry, DeferredToolsetSummary
from quickapp.config.tool_discovery import WindowSearchStrategyConfig
from quickapp.tool_discovery._anonymous_agent import RoutingResult
from quickapp.tool_discovery._routing_prompt import render_catalog_line

from ._strategy import BaseStrategy, sum_routing_usage

_MAX_PARALLEL_WINDOW_CALLS = 8


def split_into_windows(
    catalog: list[DeferredToolCatalogEntry], max_chars: int
) -> list[list[DeferredToolCatalogEntry]]:
    """Group consecutive entries so that a window's rendered text stays within max_chars.

    An entry that alone exceeds max_chars gets a window of its own.
    """
    windows: list[list[DeferredToolCatalogEntry]] = []
    current: list[DeferredToolCatalogEntry] = []
    current_chars = 0
    for entry in catalog:
        entry_chars = len(render_catalog_line(entry)) + 1
        if current and current_chars + entry_chars > max_chars:
            windows.append(current)
            current, current_chars = [], 0
        current.append(entry)
        current_chars += entry_chars
    if current:
        windows.append(current)
    return windows


class WindowStrategy(BaseStrategy[WindowSearchStrategyConfig]):
    """Searches catalog windows in parallel, then filters the union of the candidates."""

    async def search(
        self,
        query: str,
        catalog: list[DeferredToolCatalogEntry],
        toolset_summaries: list[DeferredToolsetSummary],
    ) -> RoutingResult:
        del toolset_summaries  # unused by this strategy
        windows = split_into_windows(catalog, self._config.window_size_chars)
        if len(windows) <= 1:
            return await self._route_tools(query, catalog)

        semaphore = asyncio.Semaphore(_MAX_PARALLEL_WINDOW_CALLS)

        async def search_window(window: list[DeferredToolCatalogEntry]) -> RoutingResult:
            async with semaphore:
                return await self._route_tools(query, window, limit=self._config.per_window_top_k)

        window_results = await asyncio.gather(*(search_window(window) for window in windows))
        candidate_names = list(dict.fromkeys(name for r in window_results for name in r.names))
        if not candidate_names:
            return RoutingResult(usage=sum_routing_usage(*window_results))

        entries_by_name = {entry["name"]: entry for entry in catalog}
        final = await self._route_tools(query, [entries_by_name[name] for name in candidate_names])
        return final.with_usage(sum_routing_usage(*window_results, final))
