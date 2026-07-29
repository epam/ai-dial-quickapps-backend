from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.config.dial_deployment import DialDeploymentConfig, DialDeploymentParameters
from quickapp.config.tools.base import (
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.deployment import ConversationMode, DialDeploymentTool
from quickapp.config.tools.deployment_simple import DialDeploymentSimpleTool
from quickapp.config.toolsets.deployment import DeploymentToolSet
from quickapp.dial_deployment_tooling._deployment_tool_initializer import _DeploymentToolInitializer
from tests.unit_tests.common.common import make_provider


def _make_deployment_tool(name: str) -> DialDeploymentTool:
    return DialDeploymentTool(
        deployment=DialDeploymentConfig(
            deployment_id="my-app", parameters=DialDeploymentParameters()
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
        tool_config_service=MagicMock(),
        builder=builder,
        deployment_cache=MagicMock(),
        dial_tools_provider=make_provider(dial_tools),
        simple_tools_provider=make_provider([]),
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
        tool_config_service=MagicMock(),
        builder=builder,
        deployment_cache=deployment_cache,
        dial_tools_provider=make_provider([]),
        simple_tools_provider=make_provider([simple_tool]),
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
