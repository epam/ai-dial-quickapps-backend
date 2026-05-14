from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Message, Role

from quickapp.common import ToolCallResult
from quickapp.common.staged_base_tool import StageLevel
from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency
from quickapp.common.synthetic_injection.staged_tool_synthetic_injector import (
    StagedToolSyntheticInjector,
)
from tests.unit_tests.common.common import make_provider


def _make_staged_tool(sanitized_name: str, run_content: str = "tool result") -> MagicMock:
    """Build a minimal StagedBaseTool-like mock keyed by sanitized name."""
    tool_fn = SimpleNamespace(name=sanitized_name)
    tool_open_ai = SimpleNamespace(function=tool_fn)
    tool_config = SimpleNamespace(open_ai_tool=tool_open_ai)

    result = ToolCallResult(content=run_content, content_type="text/plain")
    arun_mock = AsyncMock(return_value=result)

    tool = MagicMock()
    tool.tool_config = tool_config
    tool.arun = arun_mock
    return tool


class _ConcreteInjector(StagedToolSyntheticInjector):
    def __init__(self, tools, tool_name: str):
        super().__init__(tools, enrichers_provider=make_provider([]))
        self._tool_name = tool_name

    async def get_tool_name(self) -> str:
        return self._tool_name

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return InjectionFrequency.ALWAYS


class TestStagedToolSyntheticInjector:

    @pytest.mark.asyncio
    async def test_calls_arun_and_returns_content(self):
        tool = _make_staged_tool("my_tool", "hello from tool")
        injector = _ConcreteInjector([tool], "my_tool")

        messages = [Message(role=Role.USER, content="hi")]
        result = await injector.transform(messages)

        assert len(result) == 3
        assert result[2].content == "hello from tool"
        tool.arun.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_when_tool_not_found(self):
        tool = _make_staged_tool("other_tool")
        injector = _ConcreteInjector([tool], "missing_tool")

        messages = [Message(role=Role.USER, content="hi")]
        result = await injector.transform(messages)

        assert result is messages
        tool.arun.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_passes_arguments_to_arun(self):
        tool = _make_staged_tool("arg_tool", "result")
        injector = _ConcreteInjector([tool], "arg_tool")
        # Override get_arguments for this test
        injector.get_arguments = AsyncMock(return_value={"key": "value"})

        messages = [Message(role=Role.USER, content="hi")]
        await injector.transform(messages)

        _, kwargs = tool.arun.call_args
        assert kwargs.get("key") == "value"

    @pytest.mark.asyncio
    async def test_passes_stage_level_system(self):
        tool = _make_staged_tool("my_tool", "result")
        injector = _ConcreteInjector([tool], "my_tool")

        messages = [Message(role=Role.USER, content="hi")]
        await injector.transform(messages)

        _, kwargs = tool.arun.call_args
        assert kwargs.get("stage_level") == StageLevel.SYSTEM

    @pytest.mark.asyncio
    async def test_multiple_tools_correct_one_selected(self):
        tool_a = _make_staged_tool("tool_a", "from a")
        tool_b = _make_staged_tool("tool_b", "from b")
        injector = _ConcreteInjector([tool_a, tool_b], "tool_b")

        messages = [Message(role=Role.USER, content="hi")]
        result = await injector.transform(messages)

        assert result[2].content == "from b"
        tool_a.arun.assert_not_awaited()
        tool_b.arun.assert_awaited_once()
