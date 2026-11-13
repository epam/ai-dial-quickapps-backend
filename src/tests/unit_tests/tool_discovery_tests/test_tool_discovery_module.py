from unittest.mock import MagicMock

import pytest
from injector import Binder, Injector

from quickapp.common.deferred_tool_types import DeferredToolCatalogEntry, DeferredToolsetSummary
from quickapp.config.application import ApplicationConfig
from quickapp.config.tool_discovery import (
    HierarchySearchStrategyConfig,
    PlainSearchStrategyConfig,
    WindowSearchStrategyConfig,
)
from quickapp.tool_discovery._anonymous_agent import _AnonymousAgent
from quickapp.tool_discovery._tool_search_hint_prompt_provider import _ToolSearchHintPromptProvider
from quickapp.tool_discovery.strategies import (
    HierarchyStrategy,
    PlainStrategy,
    ToolSearchStrategy,
    WindowStrategy,
)
from quickapp.tool_discovery.tool_discovery_module import ToolDiscoveryModule


def _make_config(enabled: bool | None) -> MagicMock:
    config = MagicMock()
    if enabled is None:
        config.orchestrator.tool_discovery = None
    else:
        config.orchestrator.tool_discovery.enabled = enabled
    return config


class TestProvidePromptParts:
    def test_includes_hint_when_discovery_enabled(self):
        module = ToolDiscoveryModule()
        tool_search_hint = MagicMock(spec=_ToolSearchHintPromptProvider)

        result = module._provide_prompt_parts(_make_config(True), tool_search_hint)

        assert result == [tool_search_hint]

    def test_omits_hint_when_discovery_disabled(self):
        module = ToolDiscoveryModule()
        tool_search_hint = MagicMock(spec=_ToolSearchHintPromptProvider)

        result = module._provide_prompt_parts(_make_config(False), tool_search_hint)

        assert result == []

    def test_omits_hint_when_discovery_unset(self):
        module = ToolDiscoveryModule()
        tool_search_hint = MagicMock(spec=_ToolSearchHintPromptProvider)

        result = module._provide_prompt_parts(_make_config(None), tool_search_hint)

        assert result == []


class TestProvideToolSearchTools:
    def test_returns_empty_list_when_discovery_disabled(self):
        module = ToolDiscoveryModule()
        tool_builder = MagicMock()

        result = module._provide_tool_search_tools(_make_config(False), tool_builder)

        assert result == []
        tool_builder.build.assert_not_called()

    def test_builds_tool_when_discovery_enabled(self):
        module = ToolDiscoveryModule()
        tool_builder = MagicMock()
        built_tool = MagicMock()
        tool_builder.build.return_value = built_tool

        result = module._provide_tool_search_tools(_make_config(True), tool_builder)

        assert result == [built_tool]


class TestProvideSearchStrategy:
    @pytest.mark.parametrize(
        ("strategy_config", "expected"),
        [
            (PlainSearchStrategyConfig(), PlainStrategy),
            (WindowSearchStrategyConfig(), WindowStrategy),
            (HierarchySearchStrategyConfig(), HierarchyStrategy),
        ],
    )
    def test_maps_config_to_strategy(self, strategy_config, expected):
        config = _make_config(True)
        config.orchestrator.tool_discovery.strategy = strategy_config

        result = ToolDiscoveryModule()._provide_search_strategy(config, MagicMock(), [], [])

        assert type(result) is expected

    def test_resolves_strategy_through_injector(self):
        config = _make_config(True)
        config.orchestrator.tool_discovery.strategy = HierarchySearchStrategyConfig()

        def configure(binder: Binder) -> None:
            binder.bind(ApplicationConfig, to=config)
            binder.bind(_AnonymousAgent, to=MagicMock(spec=_AnonymousAgent))
            binder.multibind(list[DeferredToolCatalogEntry], to=[])
            binder.multibind(list[DeferredToolsetSummary], to=[])

        strategy = Injector([ToolDiscoveryModule(), configure]).get(ToolSearchStrategy)

        assert type(strategy) is HierarchyStrategy
