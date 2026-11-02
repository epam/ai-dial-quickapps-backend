import asyncio

from quickapp.common.deferred_tool_types import DeferredToolCatalogEntry, DeferredToolsetSummary
from quickapp.config.tool_discovery import WindowSearchStrategy
from quickapp.tool_discovery._anonymous_agent import (
    _AnonymousAgent,
    _RoutingResult,
    sum_routing_usage,
)
from quickapp.tool_discovery.strategies._selection import render_catalog_line


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


class WindowStrategy:
    """Searches catalog windows in parallel, then filters the union of the candidates."""

    def __init__(self, agent: _AnonymousAgent, settings: WindowSearchStrategy) -> None:
        self.__agent = agent
        self.__settings = settings

    async def search(
        self,
        query: str,
        catalog: list[DeferredToolCatalogEntry],
        toolset_summaries: list[DeferredToolsetSummary],
    ) -> _RoutingResult:
        settings = self.__settings
        windows = split_into_windows(catalog, settings.window_size_chars)
        if len(windows) <= 1:
            return await self.__agent.route(
                query,
                catalog,
                kind="tool",
                limit=settings.top_k,
                threshold=settings.score_threshold,
            )

        window_results = await asyncio.gather(
            *(
                self.__agent.route(
                    query,
                    window,
                    kind="tool",
                    limit=settings.per_window_top_k,
                    threshold=settings.score_threshold,
                )
                for window in windows
            )
        )
        candidate_names = list(dict.fromkeys(name for r in window_results for name in r.names))
        window_usage = sum_routing_usage(*window_results)
        if not candidate_names:
            return _RoutingResult(usage=window_usage)

        entries_by_name = {entry["name"]: entry for entry in catalog}
        final = await self.__agent.route(
            query,
            [entries_by_name[name] for name in candidate_names],
            kind="tool",
            limit=settings.top_k,
            threshold=settings.score_threshold,
        )
        return final.with_usage(sum_routing_usage(_RoutingResult(usage=window_usage), final))
