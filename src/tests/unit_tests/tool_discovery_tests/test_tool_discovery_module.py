from unittest.mock import MagicMock

import pytest
from aidial_sdk.chat_completion import CustomContent, Message, Role
from fastapi_injector import Injected, request_scope
from injector import Binder, Injector
from starlette.testclient import TestClient

from quickapp.common import REQUEST_MESSAGES
from quickapp.common.deferred_tool_types import (
    DeferredToolCatalogEntry,
    DeferredToolDefinition,
    DeferredToolsetSummary,
)
from quickapp.common.state_holder import StateHolder
from quickapp.config.application import ApplicationConfig
from quickapp.config.tool_discovery import (
    HierarchySearchStrategyConfig,
    PlainSearchStrategyConfig,
    WindowSearchStrategyConfig,
)
from quickapp.core.agent.lazy_loaded_tools_holder import LazyLoadedToolsHolder
from quickapp.tool_discovery._anonymous_agent import _AnonymousAgent
from quickapp.tool_discovery._discovered_tools_state import DISCOVERED_TOOLS_STATE_KEY
from quickapp.tool_discovery._persisted_tools_holder import _PersistedToolsHolder
from quickapp.tool_discovery._tool_search_hint_prompt_provider import _ToolSearchHintPromptProvider
from quickapp.tool_discovery.strategies import (
    HierarchyStrategy,
    PlainStrategy,
    ToolSearchStrategy,
    WindowStrategy,
)
from quickapp.tool_discovery.tool_discovery_module import ToolDiscoveryModule
from tests.unit_tests.common.common import create_test_app


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


def _definition(name: str) -> DeferredToolDefinition:
    return DeferredToolDefinition(
        name=name, definition={"type": "function", "function": {"name": name}}
    )


def _assistant_with_discovered(names: list[str]) -> Message:
    return Message(
        role=Role.ASSISTANT,
        content="ok",
        custom_content=CustomContent(state={DISCOVERED_TOOLS_STATE_KEY: names}),
    )


def _provide_holder(
    definitions: list[DeferredToolDefinition],
    messages: list[Message],
    state_holder: StateHolder,
) -> LazyLoadedToolsHolder:
    provider_of = MagicMock()
    provider_of.get.side_effect = lambda: definitions
    return _PersistedToolsHolder(state_holder, messages, provider_of)


class TestPersistedToolsHolder:
    def test_restores_tools_in_discovery_order_and_drops_stale_names(self):
        state_holder = StateHolder()

        holder = _provide_holder(
            [_definition("a"), _definition("b"), _definition("c")],
            [_assistant_with_discovered(["c", "gone", "a"])],
            state_holder,
        )

        assert holder.names == ["c", "a"]
        assert state_holder.get_state() == {DISCOVERED_TOOLS_STATE_KEY: ["c", "a"]}

    def test_writes_nothing_on_a_conversation_without_discovery(self):
        state_holder = StateHolder()

        holder = _provide_holder(
            [_definition("a")], [Message(role=Role.USER, content="hi")], state_holder
        )

        assert holder.names == []
        assert state_holder.get_state() == {}

    def test_persists_empty_list_when_every_restored_name_is_stale(self):
        state_holder = StateHolder()

        holder = _provide_holder([], [_assistant_with_discovered(["gone"])], state_holder)

        assert holder.names == []
        assert state_holder.get_state() == {DISCOVERED_TOOLS_STATE_KEY: []}

    def test_newly_discovered_tools_extend_the_persisted_names(self):
        state_holder = StateHolder()
        holder = _provide_holder(
            [_definition("a"), _definition("b")], [_assistant_with_discovered(["a"])], state_holder
        )

        holder.add([_definition("b").definition])

        assert state_holder.get_state() == {DISCOVERED_TOOLS_STATE_KEY: ["a", "b"]}

    def test_reads_definitions_on_first_use_not_on_creation(self):
        # REST and internal tools register their deferred definitions while the tool list is
        # built, which may happen after the holder is created.
        definitions: list[DeferredToolDefinition] = []
        holder = _provide_holder(definitions, [_assistant_with_discovered(["a"])], StateHolder())

        definitions.append(_definition("a"))

        assert holder.names == ["a"]


class TestHolderSharing:
    def test_every_consumer_gets_the_same_holder_within_a_request(self):
        def configure(binder: Binder) -> None:
            binder.bind(StateHolder, to=StateHolder(), scope=request_scope)
            binder.multibind(list[DeferredToolDefinition], to=[])
            binder.multibind(REQUEST_MESSAGES, to=[])

        app = create_test_app([ToolDiscoveryModule(), configure])
        seen: list[LazyLoadedToolsHolder] = []

        @app.get("/holders")
        async def holders(
            first: LazyLoadedToolsHolder = Injected(LazyLoadedToolsHolder),
            second: LazyLoadedToolsHolder = Injected(LazyLoadedToolsHolder),
        ) -> None:
            seen.extend([first, second])

        TestClient(app).get("/holders")
        TestClient(app).get("/holders")

        assert seen[0] is seen[1]
        assert seen[2] is seen[3]
        assert seen[0] is not seen[2]
