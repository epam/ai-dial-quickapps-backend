from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Message, Role

from quickapp.agent_hooks._config_driven_hooks import _ConfigDrivenToolCallHook
from quickapp.common import ToolCallResult
from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency
from quickapp.config.hooks import HookEvent, ToolCallHookConfig


def _make_staged_tool(sanitized_name: str, run_content: str = "tool result") -> MagicMock:
    tool_fn = SimpleNamespace(name=sanitized_name)
    tool_open_ai = SimpleNamespace(function=tool_fn)
    tool_config = SimpleNamespace(open_ai_tool=tool_open_ai)
    result = ToolCallResult(content=run_content, content_type="text/plain")
    tool = MagicMock()
    tool.tool_config = tool_config
    tool.arun = AsyncMock(return_value=result)
    return tool


def _make_hook(
    tool_name: str,
    toolset_name: str | None = None,
    frequency: InjectionFrequency = InjectionFrequency.ALWAYS,
    arguments: dict | None = None,
    tools: list | None = None,
) -> _ConfigDrivenToolCallHook:
    config = ToolCallHookConfig(
        event=HookEvent.ON_REQUEST_START,
        tool_name=tool_name,
        toolset_name=toolset_name,
        frequency=frequency,
        arguments=arguments or {},
    )
    return _ConfigDrivenToolCallHook(tools or [], config)


class TestGetToolName:
    @pytest.mark.asyncio
    async def test_without_toolset_name_returns_tool_name_verbatim(self):
        hook = _make_hook("My_Summarizer_tool")
        assert await hook.get_tool_name() == "My_Summarizer_tool"

    @pytest.mark.asyncio
    async def test_with_toolset_name_applies_sanitize_toolname(self):
        hook = _make_hook("get_memories", toolset_name="memory_server")
        assert await hook.get_tool_name() == "memory_server_get_memories"

    @pytest.mark.asyncio
    async def test_toolset_name_with_special_chars_sanitized(self):
        # sanitize_toolname replaces non-[a-zA-Z0-9_-] with '_'
        hook = _make_hook("get data", toolset_name="my server")
        assert await hook.get_tool_name() == "my_server_get_data"


class TestGetArguments:
    @pytest.mark.asyncio
    async def test_returns_config_arguments(self):
        hook = _make_hook("tool", arguments={"user_id": "abc", "limit": 10})
        assert await hook.get_arguments() == {"user_id": "abc", "limit": 10}

    @pytest.mark.asyncio
    async def test_defaults_to_empty_dict(self):
        hook = _make_hook("tool")
        assert await hook.get_arguments() == {}


class TestGetFrequency:
    @pytest.mark.asyncio
    async def test_returns_config_frequency_always(self):
        hook = _make_hook("tool", frequency=InjectionFrequency.ALWAYS)
        assert await hook.get_frequency([]) == InjectionFrequency.ALWAYS

    @pytest.mark.asyncio
    async def test_returns_config_frequency_append_if_changed(self):
        hook = _make_hook("tool", frequency=InjectionFrequency.APPEND_IF_CHANGED)
        assert await hook.get_frequency([]) == InjectionFrequency.APPEND_IF_CHANGED


class TestGetContent:
    @pytest.mark.asyncio
    async def test_delegates_to_staged_injector_and_returns_content(self):
        tool = _make_staged_tool("my_tool", "hello from tool")
        hook = _make_hook("my_tool", tools=[tool])
        result = await hook.get_content([])
        assert result == "hello from tool"
        tool.arun.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_none_when_tool_not_found(self):
        tool = _make_staged_tool("other_tool")
        hook = _make_hook("missing_tool", tools=[tool])
        result = await hook.get_content([])
        assert result is None
        tool.arun.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_none_and_logs_on_arun_exception(self):
        tool = _make_staged_tool("failing_tool")
        tool.arun = AsyncMock(side_effect=RuntimeError("network error"))
        hook = _make_hook("failing_tool", tools=[tool])
        result = await hook.get_content([])
        assert result is None

    @pytest.mark.asyncio
    async def test_passes_arguments_to_arun(self):
        tool = _make_staged_tool("arg_tool", "result")
        hook = _make_hook("arg_tool", arguments={"key": "value"}, tools=[tool])
        await hook.get_content([])
        _, kwargs = tool.arun.call_args
        assert kwargs.get("key") == "value"


class TestTransformIntegration:
    @pytest.mark.asyncio
    async def test_injects_pair_into_messages(self):
        tool = _make_staged_tool("my_tool", "injected content")
        hook = _make_hook("my_tool", frequency=InjectionFrequency.ALWAYS, tools=[tool])
        messages = [Message(role=Role.USER, content="hi")]
        result = await hook.transform(messages)
        # Original USER message + ASSISTANT tool_call + TOOL result
        assert len(result) == 3
        assert result[2].content == "injected content"
