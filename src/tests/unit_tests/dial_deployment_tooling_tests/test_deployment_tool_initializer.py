from unittest.mock import MagicMock

import pytest

from quickapp.config.dial_deployment import DialDeploymentConfig, DialDeploymentParameters
from quickapp.config.tools.base import (
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.deployment import DialDeploymentTool
from quickapp.config.toolsets.deployment import DeploymentToolSet
from quickapp.dial_deployment_tooling._deployment_tool_initializer import _DeploymentToolInitializer
from tests.unit_tests.common.common import create_app_configuration


def _make_deployment_tool(name: str) -> DialDeploymentTool:
    return DialDeploymentTool(
        deployment=DialDeploymentConfig(name="my-app", parameters=DialDeploymentParameters()),
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
    return _DeploymentToolInitializer(
        context=MagicMock(),
        tool_config_service=MagicMock(),
        builder=builder,
        app_config=create_app_configuration([toolset]),
        deployment_cache=MagicMock(),
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
