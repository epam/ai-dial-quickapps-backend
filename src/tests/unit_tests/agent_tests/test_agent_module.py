from unittest.mock import MagicMock, patch

import pytest
from aidial_sdk.chat_completion.request import Function, StaticFunction, StaticTool, Tool
from aidial_sdk.exceptions import InvalidRequestError
from pydantic import SecretStr

from quickapp.config.tools.internal import InternalTool
from quickapp.core.agent.agent_module import AgentModule


def test_provide_openai_client_forwards_bearer_to_default_headers():
    module = AgentModule()
    dial_settings = MagicMock(url="https://dial.example", api_version="2024-05-01-preview")
    config = MagicMock()
    config.orchestrator.deployment.deployment_id = "orchestrator-model"

    with patch("quickapp.core.agent.agent_module.AsyncAzureOpenAI") as openai_client:
        openai_client.return_value = MagicMock()

        module.provide_openai_client(
            dial_settings=dial_settings,
            api_key=SecretStr("test-key"),
            config=config,
            forwarded_headers={"X-Request-Id": "req-1"},
            bearer=SecretStr("incoming-token"),
        )

    assert openai_client.call_args.kwargs["default_headers"] == {
        "X-Request-Id": "req-1",
        "Authorization": "Bearer incoming-token",
    }


def test_provide_openai_client_handles_missing_bearer_without_authorization_header():
    module = AgentModule()
    dial_settings = MagicMock(url="https://dial.example", api_version="2024-05-01-preview")
    config = MagicMock()
    config.orchestrator.deployment.deployment_id = "orchestrator-model"

    with patch("quickapp.core.agent.agent_module.AsyncAzureOpenAI") as openai_client:
        openai_client.return_value = MagicMock()

        module.provide_openai_client(
            dial_settings=dial_settings,
            api_key=SecretStr("test-key"),
            config=config,
            forwarded_headers={"X-Request-Id": "req-1"},
            bearer=None,
        )

    assert openai_client.call_args.kwargs["default_headers"] == {"X-Request-Id": "req-1"}


def _make_context_with_extra_tools(tools: list) -> MagicMock:
    context = MagicMock()
    context.extra_tools = tools
    return context


def test_provide_extra_openai_tools_returns_empty_when_no_extra_tools():
    module = AgentModule()
    context = _make_context_with_extra_tools([])
    result = module.provide_extra_openai_tools(context, tools=[], static_tools=[])
    assert result == []


def test_provide_extra_openai_tools_serializes_tool_correctly():
    module = AgentModule()
    tool = Tool(type="function", function=Function(name="ext_tool", description="Does something"))
    context = _make_context_with_extra_tools([tool])
    result = module.provide_extra_openai_tools(context, tools=[], static_tools=[])
    assert len(result) == 1
    assert result[0]["type"] == "function"
    assert result[0]["function"]["name"] == "ext_tool"
    assert result[0]["function"]["description"] == "Does something"


def test_provide_extra_openai_tools_raises_on_name_collision_with_server_tool():
    module = AgentModule()
    extra_tool = Tool(type="function", function=Function(name="my_tool"))

    open_ai_tool_mock = MagicMock()
    open_ai_tool_mock.function.name = "my_tool"
    tool_config = InternalTool.model_construct(open_ai_tool=open_ai_tool_mock)
    server_staged_tool = MagicMock()
    server_staged_tool.tool_config = tool_config

    context = _make_context_with_extra_tools([extra_tool])

    with pytest.raises(InvalidRequestError, match="my_tool"):
        module.provide_extra_openai_tools(context, tools=[server_staged_tool], static_tools=[])


def test_provide_extra_openai_tools_raises_on_name_collision_with_static_tool():
    module = AgentModule()
    extra_tool = Tool(type="function", function=Function(name="my_tool"))
    static_tool = StaticTool(type="static_function", static_function=StaticFunction(name="my_tool"))

    context = _make_context_with_extra_tools([extra_tool])

    with pytest.raises(InvalidRequestError, match="my_tool"):
        module.provide_extra_openai_tools(context, tools=[], static_tools=[static_tool])


def test_provide_tool_names_returns_frozenset_of_extra_tool_names():
    module = AgentModule()
    context = _make_context_with_extra_tools(
        [
            Tool(type="function", function=Function(name="tool_a")),
            Tool(type="function", function=Function(name="tool_b")),
        ]
    )
    result = module.provide_tool_names(context)
    assert result == frozenset({"tool_a", "tool_b"})


def test_provide_tool_names_returns_empty_frozenset_when_no_extra_tools():
    module = AgentModule()
    context = _make_context_with_extra_tools([])
    result = module.provide_tool_names(context)
    assert result == frozenset()
