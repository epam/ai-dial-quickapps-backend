import json
from unittest.mock import AsyncMock, MagicMock

import openai
import pytest
from pydantic import TypeAdapter, ValidationError

from quickapp.common.deployment_usage import ModelUsage
from quickapp.config.tool_discovery import (
    HierarchySearchStrategy,
    PlainSearchStrategy,
    SearchStrategy,
    ToolDiscoveryConfig,
    WindowSearchStrategy,
)
from quickapp.tool_discovery._anonymous_agent import _AnonymousAgent, _RoutingResult
from quickapp.tool_discovery.strategies._hierarchy import HierarchyStrategy
from quickapp.tool_discovery.strategies._plain import PlainStrategy
from quickapp.tool_discovery.strategies._window import WindowStrategy, split_into_windows


def _make_selector(content: str | Exception, service_model: str | None = None):
    config = MagicMock()
    config.orchestrator.deployment.deployment_id = "orchestrator-model"
    config.orchestrator.tool_discovery.service_model = service_model
    client = AsyncMock()
    if isinstance(content, Exception):
        client.chat.completions.create.side_effect = content
    else:
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = content
        client.chat.completions.create.return_value = response
    return _AnonymousAgent(client=client, config=config), client


def _entry(name: str, toolset: str = "ts", description: str = "d") -> dict[str, str]:
    return {"name": name, "description": description, "toolset": toolset}


CANDIDATES = [_entry("tool_a"), _entry("tool_b"), _entry("tool_c")]


async def _select(selector, limit=10, threshold=0.5, candidates=CANDIDATES):
    result = await selector.route(
        "query", candidates, kind="tool", limit=limit, threshold=threshold
    )
    return result.names


class TestAnonymousAgentRouting:
    @pytest.mark.asyncio
    async def test_empty_candidates_skip_the_call(self):
        selector, client = _make_selector("[]")
        assert await _select(selector, candidates=[]) == []
        client.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_sorts_by_score_and_applies_threshold_and_limit(self):
        raw = json.dumps(
            [
                {"name": "tool_a", "score": 0.6},
                {"name": "tool_b", "score": 0.9},
                {"name": "tool_c", "score": 0.2},
            ]
        )
        selector, _ = _make_selector(raw)
        assert await _select(selector) == ["tool_b", "tool_a"]
        assert await _select(selector, limit=1) == ["tool_b"]

    @pytest.mark.asyncio
    async def test_strips_fences_and_accepts_plain_names(self):
        selector, _ = _make_selector('```json\n["tool_a", "tool_b"]\n```')
        assert await _select(selector) == ["tool_a", "tool_b"]

    @pytest.mark.asyncio
    async def test_drops_unknown_and_duplicate_names(self):
        selector, _ = _make_selector('["ghost", "tool_a", "tool_a", 5]')
        assert await _select(selector) == ["tool_a"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("raw", ["not json", "[1, 2", "", "{}"])
    async def test_unparsable_answer_yields_empty(self, raw):
        selector, _ = _make_selector(raw)
        assert await _select(selector) == []

    @pytest.mark.asyncio
    async def test_openai_error_yields_empty(self):
        selector, _ = _make_selector(openai.OpenAIError("boom"))
        assert await _select(selector) == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("service_model", "expected"), [("svc", "svc"), (None, "orchestrator-model")]
    )
    async def test_model_selection(self, service_model, expected):
        selector, client = _make_selector("[]", service_model=service_model)
        await _select(selector)
        assert client.chat.completions.create.call_args.kwargs["model"] == expected


def _usage(tokens: int) -> ModelUsage:
    return ModelUsage(model="m", prompt_tokens=tokens, completion_tokens=1)


def _stub_selector(*results: list[str]) -> MagicMock:
    selector = MagicMock()
    selector.route = AsyncMock(
        side_effect=[_RoutingResult(names=list(r), usage=_usage(10)) for r in results]
    )
    return selector


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
        selector = _stub_selector(["tool_a"])
        strategy = PlainStrategy(selector, PlainSearchStrategy(top_k=4, score_threshold=0.7))
        assert (await strategy.search("q", CANDIDATES, [])).names == ["tool_a"]
        kwargs = selector.route.call_args.kwargs
        assert (kwargs["limit"], kwargs["threshold"], kwargs["kind"]) == (4, 0.7, "tool")


class TestWindowStrategy:
    @pytest.mark.asyncio
    async def test_single_window_makes_one_call(self):
        selector = _stub_selector(["tool_a"])
        strategy = WindowStrategy(selector, WindowSearchStrategy(top_k=5))
        assert (await strategy.search("q", CANDIDATES, [])).names == ["tool_a"]
        assert selector.route.await_count == 1
        assert selector.route.call_args.kwargs["limit"] == 5

    @pytest.mark.asyncio
    async def test_windows_then_final_filter(self):
        catalog = [_entry(f"t{i}", description="x" * 600) for i in range(3)]
        settings = WindowSearchStrategy(window_size_chars=1000, per_window_top_k=2, top_k=3)
        # one entry per window; the window results overlap on t1
        selector = _stub_selector(["t0"], ["t1"], ["t1", "t2"], ["t2", "t0"])
        strategy = WindowStrategy(selector, settings)
        result = await strategy.search("q", catalog, [])
        assert result.names == ["t2", "t0"]
        assert result.usage == ModelUsage(model="m", prompt_tokens=40, completion_tokens=4)
        assert selector.route.await_count == 4
        final = selector.route.call_args_list[-1]
        assert [e["name"] for e in final.args[1]] == ["t0", "t1", "t2"]
        assert final.kwargs["limit"] == 3

    @pytest.mark.asyncio
    async def test_no_candidates_skips_final_call(self):
        catalog = [_entry(f"t{i}", description="x" * 600) for i in range(2)]
        selector = _stub_selector([], [])
        strategy = WindowStrategy(selector, WindowSearchStrategy(window_size_chars=1000))
        result = await strategy.search("q", catalog, [])
        assert result.names == []
        assert result.usage == ModelUsage(model="m", prompt_tokens=20, completion_tokens=2)
        assert selector.route.await_count == 2


class TestHierarchyStrategy:
    CATALOG = [_entry("a1", "A"), _entry("a2", "A"), _entry("b1", "B")]
    SUMMARIES = [{"name": "A"}, {"name": "B"}]

    @pytest.mark.asyncio
    async def test_scopes_second_stage_to_chosen_toolsets(self):
        selector = _stub_selector(["B"], ["b1"])
        strategy = HierarchyStrategy(selector, HierarchySearchStrategy(toolset_top_k=1))
        result = await strategy.search("q", self.CATALOG, self.SUMMARIES)
        assert result.names == ["b1"]
        assert result.usage == ModelUsage(model="m", prompt_tokens=20, completion_tokens=2)
        first, second = selector.route.call_args_list
        assert first.kwargs["kind"] == "toolset" and first.kwargs["limit"] == 1
        assert [e["name"] for e in second.args[1]] == ["b1"]

    @pytest.mark.asyncio
    async def test_falls_back_to_whole_catalog_when_no_toolset(self):
        selector = _stub_selector([], ["a1"])
        strategy = HierarchyStrategy(selector, HierarchySearchStrategy())
        assert (await strategy.search("q", self.CATALOG, self.SUMMARIES)).names == ["a1"]
        assert len(selector.route.call_args_list[1].args[1]) == 3

    @pytest.mark.asyncio
    async def test_single_toolset_skips_first_stage(self):
        selector = _stub_selector(["a1"])
        strategy = HierarchyStrategy(selector, HierarchySearchStrategy())
        assert (await strategy.search("q", self.CATALOG, [{"name": "A"}])).names == ["a1"]
        assert selector.route.await_count == 1


class TestStrategyConfig:
    def test_default_is_plain(self):
        config = ToolDiscoveryConfig()
        assert isinstance(config.strategy, PlainSearchStrategy)
        assert (config.strategy.top_k, config.strategy.score_threshold) == (10, 0.5)

    @pytest.mark.parametrize(
        ("type_", "cls"),
        [
            ("plain", PlainSearchStrategy),
            ("window", WindowSearchStrategy),
            ("hierarchy", HierarchySearchStrategy),
        ],
    )
    def test_discriminator(self, type_, cls):
        assert isinstance(TypeAdapter(SearchStrategy).validate_python({"type": type_}), cls)

    def test_window_defaults(self):
        strategy = WindowSearchStrategy()
        assert (strategy.window_size_chars, strategy.per_window_top_k) == (40000, 3)

    def test_unknown_type_and_bad_threshold_rejected(self):
        with pytest.raises(ValidationError):
            ToolDiscoveryConfig(strategy={"type": "bogus"})
        with pytest.raises(ValidationError):
            PlainSearchStrategy(score_threshold=1.5)
