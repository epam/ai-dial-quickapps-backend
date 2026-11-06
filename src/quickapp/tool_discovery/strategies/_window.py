import asyncio

from quickapp.common.deferred_tool_types import DeferredToolCatalogEntry
from quickapp.config.tool_discovery import WindowSearchStrategyConfig
from quickapp.tool_discovery._routing_prompt import render_catalog_line
from quickapp.tool_discovery._routing_result import RoutingResult
from quickapp.tool_discovery.strategies._strategy import ToolSearchStrategy

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


class WindowStrategy(ToolSearchStrategy[WindowSearchStrategyConfig]):
    """Searches catalog windows in parallel, then filters the union of the candidates."""

    async def search(self, query: str) -> RoutingResult:
        windows = split_into_windows(self._catalog, self._config.window_size_chars)
        if len(windows) <= 1:
            return await self._route_tools(query, self._catalog)

        window_results = await self._search_windows(query, windows)
        candidate_names = list(dict.fromkeys(name for r in window_results for name in r.names))
        if not candidate_names:
            return RoutingResult(usage=RoutingResult.total_usage(*window_results))
        if len(candidate_names) == 1:
            # nothing to filter or re-rank: skip the final LLM round-trip
            return RoutingResult(
                names=candidate_names, usage=RoutingResult.total_usage(*window_results)
            )

        entries_by_name = {entry["name"]: entry for entry in self._catalog}
        final = await self._route_tools(query, [entries_by_name[name] for name in candidate_names])
        return RoutingResult(
            names=final.names, usage=RoutingResult.total_usage(*window_results, final)
        )

    async def _search_windows(
        self, query: str, windows: list[list[DeferredToolCatalogEntry]]
    ) -> list[RoutingResult]:
        """Route every window with bounded parallelism."""
        semaphore = asyncio.Semaphore(_MAX_PARALLEL_WINDOW_CALLS)

        async def search_window(window: list[DeferredToolCatalogEntry]) -> RoutingResult:
            async with semaphore:
                return await self._route_tools(query, window, limit=self._config.per_window_top_k)

        return list(await asyncio.gather(*(search_window(window) for window in windows)))
