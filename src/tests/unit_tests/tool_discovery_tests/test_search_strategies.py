from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import TypeAdapter, ValidationError

from quickapp.common.deferred_tool_types import DeferredToolCatalogEntry, DeferredToolsetSummary
from quickapp.common.deployment_usage import ModelUsage
from quickapp.config.tool_discovery import (
    HierarchySearchStrategyConfig,
    PlainSearchStrategyConfig,
    SearchStrategyConfig,
    ToolDiscoveryConfig,
    WindowSearchStrategyConfig,
)
from quickapp.tool_discovery._routing_result import RoutingResult
from quickapp.tool_discovery.strategies import HierarchyStrategy, PlainStrategy, WindowStrategy
from quickapp.tool_discovery.strategies._window import split_into_windows


def _entry(name: str, toolset: str = "ts", description: str = "d") -> DeferredToolCatalogEntry:
    return {"name": name, "description": description, "toolset": toolset}


CANDIDATES = [_entry("tool_a"), _entry("tool_b"), _entry("tool_c")]


def _usage(tokens: int) -> ModelUsage:
    return ModelUsage(model="m", prompt_tokens=tokens, completion_tokens=1)


def _stub_agent(*results: list[str]) -> MagicMock:
    agent = MagicMock()
    agent.route = AsyncMock(
        side_effect=[RoutingResult(names=list(r), usage=_usage(10)) for r in results]
    )
    return agent


class TestSplitIntoWindows:
    def test_groups_by_chars(self):
        catalog = [_entry(f"t{i}", description="x" * 20) for i in range(6)]
        line = len("- t0: " + "x" * 20) + 1
        windows = split_into_windows(catalog, line * 2)
        assert [len(w) for w in windows] == [2, 2, 2]

    def test_oversize_entry_gets_own_window(self):
        catalog = [_entry("a"), _entry("big", description="x" * 500), _entry("b")]
        assert [[e["name"] for e in w] for w in split_into_windows(catalog, 100)] == [
            ["a"],
            ["big"],
            ["b"],
        ]

    def test_empty(self):
        assert split_into_windows([], 100) == []


class TestPlainStrategy:
    @pytest.mark.asyncio
    async def test_passes_settings(self):
        agent = _stub_agent(["tool_a"])
        strategy = PlainStrategy(
            agent, PlainSearchStrategyConfig(top_k=4, score_threshold=0.7), CANDIDATES
        )
        assert (await strategy.search("q")).names == ["tool_a"]
        kwargs = agent.route.call_args.kwargs
        assert (kwargs["limit"], kwargs["threshold"], kwargs["kind"]) == (4, 0.7, "tool")


class TestWindowStrategy:
    @pytest.mark.asyncio
    async def test_single_window_makes_one_call(self):
        agent = _stub_agent(["tool_a"])
        strategy = WindowStrategy(agent, WindowSearchStrategyConfig(top_k=5), CANDIDATES)
        assert (await strategy.search("q")).names == ["tool_a"]
        assert agent.route.await_count == 1
        assert agent.route.call_args.kwargs["limit"] == 5

    @pytest.mark.asyncio
    async def test_windows_then_final_filter(self):
        catalog = [_entry(f"t{i}", description="x" * 600) for i in range(3)]
        settings = WindowSearchStrategyConfig(window_size_chars=1000, per_window_top_k=2, top_k=3)
        # one entry per window; the window results overlap on t1
        agent = _stub_agent(["t0"], ["t1"], ["t1", "t2"], ["t2", "t0"])
        strategy = WindowStrategy(agent, settings, catalog)
        result = await strategy.search("q")
        assert result.names == ["t2", "t0"]
        assert result.usage == ModelUsage(model="m", prompt_tokens=40, completion_tokens=4)
        assert agent.route.await_count == 4
        final = agent.route.call_args_list[-1]
        assert [e["name"] for e in final.args[1]] == ["t0", "t1", "t2"]
        assert final.kwargs["limit"] == 3

    @pytest.mark.asyncio
    async def test_no_candidates_skips_final_call(self):
        catalog = [_entry(f"t{i}", description="x" * 600) for i in range(2)]
        agent = _stub_agent([], [])
        strategy = WindowStrategy(
            agent, WindowSearchStrategyConfig(window_size_chars=1000), catalog
        )
        result = await strategy.search("q")
        assert result.names == []
        assert result.usage == ModelUsage(model="m", prompt_tokens=20, completion_tokens=2)
        assert agent.route.await_count == 2

    @pytest.mark.asyncio
    async def test_single_candidate_skips_final_call(self):
        catalog = [_entry(f"t{i}", description="x" * 600) for i in range(2)]
        agent = _stub_agent(["t1"], [])
        strategy = WindowStrategy(
            agent, WindowSearchStrategyConfig(window_size_chars=1000), catalog
        )
        result = await strategy.search("q")
        assert result.names == ["t1"]
        assert result.usage == ModelUsage(model="m", prompt_tokens=20, completion_tokens=2)
        assert agent.route.await_count == 2


class TestHierarchyStrategy:
    CATALOG = [_entry("a1", "A"), _entry("a2", "A"), _entry("b1", "B")]
    SUMMARIES: list[DeferredToolsetSummary] = [
        {"name": "A", "description": None, "tool_count": 2},
        {"name": "B", "description": None, "tool_count": 1},
    ]

    @pytest.mark.asyncio
    async def test_scopes_second_stage_to_chosen_toolsets(self):
        agent = _stub_agent(["B"], ["b1"])
        strategy = HierarchyStrategy(
            agent, HierarchySearchStrategyConfig(toolset_top_k=1), self.CATALOG, self.SUMMARIES
        )
        result = await strategy.search("q")
        assert result.names == ["b1"]
        assert result.usage == ModelUsage(model="m", prompt_tokens=20, completion_tokens=2)
        first, second = agent.route.call_args_list
        assert first.kwargs["kind"] == "toolset" and first.kwargs["limit"] == 1
        assert [e["name"] for e in second.args[1]] == ["b1"]

    @pytest.mark.asyncio
    async def test_falls_back_to_whole_catalog_when_no_toolset(self):
        agent = _stub_agent([], ["a1"])
        strategy = HierarchyStrategy(
            agent, HierarchySearchStrategyConfig(), self.CATALOG, self.SUMMARIES
        )
        assert (await strategy.search("q")).names == ["a1"]
        assert len(agent.route.call_args_list[1].args[1]) == 3

    @pytest.mark.asyncio
    async def test_single_toolset_skips_first_stage(self):
        agent = _stub_agent(["a1"])
        strategy = HierarchyStrategy(
            agent, HierarchySearchStrategyConfig(), self.CATALOG, [self.SUMMARIES[0]]
        )
        assert (await strategy.search("q")).names == ["a1"]
        assert agent.route.await_count == 1


class TestStrategyConfig:
    def test_default_is_plain(self):
        config = ToolDiscoveryConfig(service_model="m")
        assert isinstance(config.strategy, PlainSearchStrategyConfig)
        assert (config.strategy.top_k, config.strategy.score_threshold) == (10, 0.5)

    @pytest.mark.parametrize(
        ("type_", "cls"),
        [
            ("plain", PlainSearchStrategyConfig),
            ("window", WindowSearchStrategyConfig),
            ("hierarchy", HierarchySearchStrategyConfig),
        ],
    )
    def test_discriminator(self, type_, cls):
        assert isinstance(TypeAdapter(SearchStrategyConfig).validate_python({"type": type_}), cls)

    def test_service_model_is_required_when_enabled(self):
        with pytest.raises(ValidationError, match="service_model"):
            ToolDiscoveryConfig(enabled=True)

    def test_service_model_is_optional_when_disabled(self):
        assert ToolDiscoveryConfig().service_model is None

    def test_window_defaults(self):
        strategy = WindowSearchStrategyConfig()
        assert (strategy.window_size_chars, strategy.per_window_top_k) == (40000, 3)

    def test_unknown_type_and_bad_threshold_rejected(self):
        with pytest.raises(ValidationError):
            ToolDiscoveryConfig(service_model="m", strategy={"type": "bogus"})
        with pytest.raises(ValidationError):
            PlainSearchStrategyConfig(score_threshold=1.5)
