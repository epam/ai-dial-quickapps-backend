from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.config.dial_deployment import DialDeploymentToolConfig, DialDeploymentToolParameters
from quickapp.config.tool_discovery import ToolDiscoveryConfig
from quickapp.config.tools.base import (
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.deployment import ConversationMode, DialDeploymentTool
from quickapp.config.tools.deployment_simple import DialDeploymentSimpleTool
from quickapp.config.toolsets.deployment import DeploymentToolSet
from quickapp.dial_deployment_tooling._deployment_deferred_tools_context import (
    _DeploymentDeferredToolsContext,
)
from quickapp.dial_deployment_tooling._deployment_tool_context import _DeploymentToolingContext
from quickapp.dial_deployment_tooling._deployment_tool_initializer import _DeploymentToolInitializer
from tests.unit_tests.common.common import create_app_configuration, make_provider


def _make_deployment_tool(name: str) -> DialDeploymentTool:
    return DialDeploymentTool(
        deployment=DialDeploymentToolConfig(
            deployment_id="my-app", parameters=DialDeploymentToolParameters()
        ),
        open_ai_tool=OpenAiToolConfig(
            function=OpenAiToolFunction(
                name=name,
                description="A test tool",
                parameters=OpenAiToolFunctionParameters(
                    type=JsonTypeEnum.object,
                    properties={},
                ),
            )
        ),
    )


def _make_initializer(toolset: DeploymentToolSet, builder: MagicMock) -> _DeploymentToolInitializer:
    dial_tools = [t for t in toolset.tools if isinstance(t, DialDeploymentTool)]
    return _DeploymentToolInitializer(
        context=MagicMock(),
        deferred_context=MagicMock(),
        tool_config_service=MagicMock(),
        builder=builder,
        deployment_cache=MagicMock(),
        dial_tools_provider=make_provider(dial_tools),
        simple_tools_provider=make_provider([]),
        app_config=create_app_configuration([toolset]),
    )


@pytest.mark.asyncio
async def test_tool_names_prefixed_with_toolset_name():
    toolset_name = "chat-hub"
    tool_name = "image_generation_tool"
    toolset = DeploymentToolSet(name=toolset_name, tools=[_make_deployment_tool(tool_name)])
    builder = MagicMock()

    await _make_initializer(toolset, builder).initialize()

    builder.build.assert_called_once()
    assert builder.build.call_args.kwargs["application_name"] == "image_generation_tool"
    assert (
        builder.build.call_args.kwargs["tool_config"].open_ai_tool.function.name
        == "image_generation_tool"
    )


@pytest.mark.asyncio
async def test_tool_names_hyphenated_toolset_name_preserved():
    toolset_name = "my-api-toolset"
    tool_name = "search_web"
    toolset = DeploymentToolSet(name=toolset_name, tools=[_make_deployment_tool(tool_name)])
    builder = MagicMock()

    await _make_initializer(toolset, builder).initialize()

    assert builder.build.call_args.kwargs["application_name"] == "search_web"
    assert builder.build.call_args.kwargs["tool_config"].open_ai_tool.function.name == "search_web"


def _make_simple_initializer(
    simple_tool: DialDeploymentSimpleTool,
    builder: MagicMock,
    cached_config: DialDeploymentTool,
) -> _DeploymentToolInitializer:
    deployment_cache = MagicMock()
    deployment_cache.fetch_basic_tool_config = AsyncMock(return_value=cached_config)
    return _DeploymentToolInitializer(
        context=MagicMock(),
        deferred_context=MagicMock(),
        tool_config_service=MagicMock(),
        builder=builder,
        deployment_cache=deployment_cache,
        dial_tools_provider=make_provider([]),
        simple_tools_provider=make_provider([simple_tool]),
        app_config=create_app_configuration([]),
    )


@pytest.mark.asyncio
async def test_simple_tool_threads_conversation_mode_onto_synthetic_config():
    simple_tool = DialDeploymentSimpleTool(
        deployment_id="my-app",
        conversation_mode=ConversationMode(resumable=True),
    )
    builder = MagicMock()
    # Synthetic config from the cache has no conversation_mode.
    cached_config = _make_deployment_tool("my_app_tool")

    await _make_simple_initializer(simple_tool, builder, cached_config).initialize()

    built_config = builder.build.call_args.kwargs["tool_config"]
    assert built_config.conversation_mode is not None
    assert built_config.conversation_mode.resumable is True
    # The cached config must not be mutated in place (model_copy produces a fresh instance).
    assert cached_config.conversation_mode is None


@pytest.mark.asyncio
async def test_simple_tool_without_conversation_mode_leaves_synthetic_default():
    simple_tool = DialDeploymentSimpleTool(deployment_id="my-app")
    builder = MagicMock()
    cached_config = _make_deployment_tool("my_app_tool")

    await _make_simple_initializer(simple_tool, builder, cached_config).initialize()

    assert builder.build.call_args.kwargs["tool_config"].conversation_mode is None


@pytest.mark.asyncio
async def test_simple_tool_threads_propagate_annotations_onto_synthetic_config():
    simple_tool = DialDeploymentSimpleTool(
        deployment_id="my-app",
        propagate_annotations_to_choice=True,
    )
    builder = MagicMock()
    cached_config = _make_deployment_tool("my_app_tool")

    await _make_simple_initializer(simple_tool, builder, cached_config).initialize()

    built_config = builder.build.call_args.kwargs["tool_config"]
    assert built_config.propagate_annotations_to_choice is True
    assert cached_config.propagate_annotations_to_choice is None


@pytest.mark.asyncio
async def test_simple_tool_threads_both_overrides_together():
    simple_tool = DialDeploymentSimpleTool(
        deployment_id="my-app",
        conversation_mode=ConversationMode(resumable=True),
        propagate_annotations_to_choice=True,
    )
    builder = MagicMock()
    cached_config = _make_deployment_tool("my_app_tool")

    await _make_simple_initializer(simple_tool, builder, cached_config).initialize()

    built_config = builder.build.call_args.kwargs["tool_config"]
    assert built_config.conversation_mode.resumable is True
    assert built_config.propagate_annotations_to_choice is True


@pytest.mark.asyncio
async def test_simple_tool_without_propagate_annotations_leaves_synthetic_default():
    simple_tool = DialDeploymentSimpleTool(deployment_id="my-app")
    builder = MagicMock()
    cached_config = _make_deployment_tool("my_app_tool")

    await _make_simple_initializer(simple_tool, builder, cached_config).initialize()

    assert builder.build.call_args.kwargs["tool_config"].propagate_annotations_to_choice is None


def _make_recording_builder() -> MagicMock:
    """Builder whose `.build()` echoes back a staged tool exposing `tool_config`."""
    builder = MagicMock()

    def _build(**kwargs):
        staged = MagicMock()
        staged.tool_config = kwargs["tool_config"]
        return staged

    builder.build.side_effect = _build
    return builder


def _make_initializer_with_discovery(
    toolset: DeploymentToolSet,
    discovery_cfg: ToolDiscoveryConfig | None,
    builder: MagicMock,
    context: _DeploymentToolingContext,
    deferred_context: _DeploymentDeferredToolsContext,
) -> _DeploymentToolInitializer:
    dial_tools = [t for t in toolset.tools if isinstance(t, DialDeploymentTool)]
    app_config = create_app_configuration([toolset])
    app_config.orchestrator.tool_discovery = discovery_cfg
    return _DeploymentToolInitializer(
        context=context,
        deferred_context=deferred_context,
        tool_config_service=MagicMock(),
        builder=builder,
        deployment_cache=MagicMock(),
        dial_tools_provider=make_provider(dial_tools),
        simple_tools_provider=make_provider([]),
        app_config=app_config,
    )


class TestDeferredDeploymentTools:
    @pytest.mark.asyncio
    async def test_registers_deferred_toolset_with_deferred_context(self):
        tools = [_make_deployment_tool("tool_one"), _make_deployment_tool("tool_two")]
        toolset = DeploymentToolSet(name="deployment", deferred=True, tools=tools)
        discovery_cfg = ToolDiscoveryConfig(enabled=True, min_tools_for_deferral=2)
        builder = _make_recording_builder()
        context = _DeploymentToolingContext()
        deferred_context = MagicMock(spec=_DeploymentDeferredToolsContext)

        initializer = _make_initializer_with_discovery(
            toolset, discovery_cfg, builder, context, deferred_context
        )
        await initializer.initialize()

        assert len(context.tools) == 2
        deferred_context.register_deferred_tools.assert_called_once()
        call_args = deferred_context.register_deferred_tools.call_args
        assert call_args.args[0] is toolset
        assert len(call_args.args[1]) == 2

    @pytest.mark.asyncio
    async def test_does_not_defer_below_threshold(self):
        tools = [_make_deployment_tool("tool_one"), _make_deployment_tool("tool_two")]
        toolset = DeploymentToolSet(name="deployment", deferred=True, tools=tools)
        discovery_cfg = ToolDiscoveryConfig(enabled=True, min_tools_for_deferral=5)
        builder = _make_recording_builder()
        context = _DeploymentToolingContext()
        deferred_context = MagicMock(spec=_DeploymentDeferredToolsContext)

        initializer = _make_initializer_with_discovery(
            toolset, discovery_cfg, builder, context, deferred_context
        )
        await initializer.initialize()

        assert len(context.tools) == 2
        deferred_context.register_deferred_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_defer_when_discovery_disabled(self):
        tools = [_make_deployment_tool("tool_one"), _make_deployment_tool("tool_two")]
        toolset = DeploymentToolSet(name="deployment", deferred=True, tools=tools)
        builder = _make_recording_builder()
        context = _DeploymentToolingContext()
        deferred_context = MagicMock(spec=_DeploymentDeferredToolsContext)

        initializer = _make_initializer_with_discovery(
            toolset,
            discovery_cfg=None,
            builder=builder,
            context=context,
            deferred_context=deferred_context,
        )
        await initializer.initialize()

        assert len(context.tools) == 2
        deferred_context.register_deferred_tools.assert_not_called()
