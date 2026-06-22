from unittest.mock import MagicMock

import pytest
from aidial_sdk.chat_completion.request import FunctionChoice, ToolChoice
from aidial_sdk.exceptions import InvalidRequestError

from quickapp.core.agent._chat_completion_config_builder import _ChatCompletionConfigBuilder
from quickapp.core.agent._tool_choice_holder import _ToolChoiceHolder


def _make_builder(
    tools=None,
    tool_choice=None,
) -> _ChatCompletionConfigBuilder:
    config = MagicMock()
    config.orchestrator.deployment.parameters.model_dump.return_value = {}
    config.orchestrator.deployment.deployment_id = "test-model"
    holder = _ToolChoiceHolder(tool_choice=tool_choice)
    return _ChatCompletionConfigBuilder(
        config=config,
        tools=tools if tools is not None else [],
        response_format=None,
        tool_choice_holder=holder,
        pre_invocation_transformers=[],
        presentation_settings=MagicMock(show_usage_statistics=False),
        forwarded_headers=None,
        agent_settings=MagicMock(chat_message_log_length=100),
    )


class TestToolChoiceInPayload:
    def test_tool_choice_none_not_in_payload(self):
        builder = _make_builder(tool_choice=None)
        result = builder.build([])
        assert "tool_choice" not in result

    def test_tool_choice_auto_included(self):
        builder = _make_builder(tool_choice="auto")
        result = builder.build([])
        assert result["tool_choice"] == "auto"

    def test_tool_choice_none_literal_included(self):
        builder = _make_builder(tool_choice="none")
        result = builder.build([])
        assert result["tool_choice"] == "none"

    def test_tool_choice_required_with_tools(self):
        tools = [{"type": "function", "function": {"name": "search", "parameters": {}}}]
        builder = _make_builder(tools=tools, tool_choice="required")
        result = builder.build([])
        assert result["tool_choice"] == "required"

    def test_tool_choice_function_object_serialized(self):
        tools = [{"type": "function", "function": {"name": "web_search", "parameters": {}}}]
        tc = ToolChoice(type="function", function=FunctionChoice(name="web_search"))
        builder = _make_builder(tools=tools, tool_choice=tc)
        result = builder.build([])
        assert result["tool_choice"] == {"type": "function", "function": {"name": "web_search"}}

    def test_tool_choice_consumed_only_on_first_build(self):
        tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]
        holder = _ToolChoiceHolder(tool_choice="required")
        config = MagicMock()
        config.orchestrator.deployment.parameters.model_dump.side_effect = lambda **kwargs: {}
        config.orchestrator.deployment.deployment_id = "model"
        builder = _ChatCompletionConfigBuilder(
            config=config,
            tools=tools,
            response_format=None,
            tool_choice_holder=holder,
            pre_invocation_transformers=[],
            presentation_settings=MagicMock(show_usage_statistics=False),
            forwarded_headers=None,
            agent_settings=MagicMock(chat_message_log_length=100),
        )
        first = builder.build([])
        assert first["tool_choice"] == "required"
        second = builder.build([])
        assert "tool_choice" not in second


class TestToolChoiceValidation:
    def test_required_without_tools_raises(self):
        builder = _make_builder(tools=[], tool_choice="required")
        with pytest.raises(InvalidRequestError):
            builder.build([])

    def test_function_object_without_tools_raises(self):
        tc = ToolChoice(type="function", function=FunctionChoice(name="my_fn"))
        builder = _make_builder(tools=[], tool_choice=tc)
        with pytest.raises(InvalidRequestError):
            builder.build([])

    def test_auto_without_tools_no_error(self):
        builder = _make_builder(tools=[], tool_choice="auto")
        result = builder.build([])
        assert result["tool_choice"] == "auto"

    def test_none_literal_without_tools_no_error(self):
        builder = _make_builder(tools=[], tool_choice="none")
        result = builder.build([])
        assert result["tool_choice"] == "none"
