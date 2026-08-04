from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.abstract.tool_call_result_processor import (
    ProcessingContext,
    ToolCallResultProcessor,
)
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.core.agent.tool_executor import ToolExecutor


def _make_tool_call(name: str, tc_id: str = "id1", arguments: str = "{}") -> MagicMock:
    tc = MagicMock()
    tc.name = name
    tc.id = tc_id
    tc.arguments = arguments
    return tc


def _make_tool(name: str, result: ToolCallResult) -> MagicMock:
    tool = MagicMock()
    tool_config = MagicMock()
    open_ai_tool = MagicMock()
    function = MagicMock()
    function.name = name
    open_ai_tool.function = function
    tool_config.open_ai_tool = open_ai_tool
    tool._tool_config = tool_config
    tool.openai_function_name = MagicMock(return_value=name)
    tool.build_argument_stream_presentation = MagicMock(return_value=None)
    tool.arun = AsyncMock(return_value=result)
    return tool


class _DoubleProcessor(ToolCallResultProcessor):
    order = 50

    async def process(self, result: ToolCallResult, ctx: ProcessingContext) -> ToolCallResult:
        return ToolCallResult(
            tool_call_id=result.tool_call_id,
            content=result.content + result.content,
            content_type=result.content_type,
        )


class _AppendProcessor(ToolCallResultProcessor):
    order = 100

    def __init__(self, suffix: str) -> None:
        self._suffix = suffix

    async def process(self, result: ToolCallResult, ctx: ProcessingContext) -> ToolCallResult:
        return ToolCallResult(
            tool_call_id=result.tool_call_id,
            content=result.content + self._suffix,
            content_type=result.content_type,
        )


class TestToolExecutorProcessors:
    @pytest.mark.asyncio
    async def test_processors_are_applied_after_enrichers(self):
        base_result = ToolCallResult(content="hello", content_type="text/plain")
        tool = _make_tool("my_tool", base_result)
        executor = ToolExecutor(
            tools=[tool],
            enrichers=[],
            perf_timer=MagicMock(),
            processors=[_AppendProcessor("!")],
        )

        results = await executor.execute([_make_tool_call("my_tool")])

        assert len(results) == 1
        assert results[0].content == "hello!"

    @pytest.mark.asyncio
    async def test_processors_run_in_order(self):
        # _DoubleProcessor (order=50) runs before _AppendProcessor (order=100)
        # "hi" → double → "hihi" → append "!" → "hihi!"
        base_result = ToolCallResult(content="hi", content_type="text/plain")
        tool = _make_tool("my_tool", base_result)
        executor = ToolExecutor(
            tools=[tool],
            enrichers=[],
            perf_timer=MagicMock(),
            processors=[_AppendProcessor("!"), _DoubleProcessor()],
        )

        results = await executor.execute([_make_tool_call("my_tool")])

        assert results[0].content == "hihi!"

    @pytest.mark.asyncio
    async def test_empty_processors_returns_original(self):
        base_result = ToolCallResult(content="original", content_type="text/plain")
        tool = _make_tool("my_tool", base_result)
        executor = ToolExecutor(
            tools=[tool],
            enrichers=[],
            perf_timer=MagicMock(),
            processors=[],
        )

        results = await executor.execute([_make_tool_call("my_tool")])

        assert results[0].content == "original"

    @pytest.mark.asyncio
    async def test_ctx_carries_tool_name_and_id(self):
        captured: list[ProcessingContext] = []

        class _CaptureProcessor(ToolCallResultProcessor):
            async def process(
                self, result: ToolCallResult, ctx: ProcessingContext
            ) -> ToolCallResult:
                captured.append(ctx)
                return result

        base_result = ToolCallResult(content="x", content_type="text/plain")
        tool = _make_tool("specific_tool", base_result)
        executor = ToolExecutor(
            tools=[tool],
            enrichers=[],
            perf_timer=MagicMock(),
            processors=[_CaptureProcessor()],
        )

        await executor.execute([_make_tool_call("specific_tool", tc_id="call_abc")])

        assert captured[0].tool_name == "specific_tool"
        assert captured[0].tool_call_id == "call_abc"
