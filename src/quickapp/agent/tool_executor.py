import asyncio
import json
import logging

from injector import inject

from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.abstract.tool_call_result_processor import (
    ProcessingContext,
    ToolCallResultProcessor,
)
from quickapp.common.chat_completion_stream.tool_call import AccumulatedToolCall
from quickapp.common.perf_timer.perf_timer import PerformanceTimer

logger = logging.getLogger(__name__)


class ToolExecutor:

    @inject
    def __init__(
        self,
        tools: list[StagedBaseTool],
        enrichers: list[ToolCallResultEnricher],
        perf_timer: PerformanceTimer,
        processors: list[ToolCallResultProcessor],
    ):
        self.__tools: dict[str, StagedBaseTool] = self.__build_tool_dict(tools)
        self.__enrichers = enrichers
        self.__processors = sorted(processors, key=lambda p: p.priority)
        self.__perf_timer: PerformanceTimer = perf_timer
        self.__period_name = "tool_execution"

    async def execute(self, tool_call_list: list[AccumulatedToolCall]) -> list[ToolCallResult]:
        tasks = []
        valid_calls: list[AccumulatedToolCall] = []
        for tc in tool_call_list:
            tool = self.__tools.get(tc.name)
            if tool:
                args = json.loads(tc.arguments)
                logger.debug(f"Making tool calls: {tc.name} with args:{args}")
                tasks.append(tool.arun(tool_call_id=tc.id, **args))
                valid_calls.append(tc)

        results: list[ToolCallResult] = list(await asyncio.gather(*tasks, return_exceptions=False))

        for enricher in self.__enrichers:
            for result in results:
                enricher.enrich(result)

        for i, (result, tc) in enumerate(zip(results, valid_calls)):
            ctx = ProcessingContext(tool_call_id=tc.id, tool_name=tc.name)
            for processor in self.__processors:
                result = await processor.process(result, ctx)
            results[i] = result

        return results

    @staticmethod
    def __build_tool_dict(tools: list[StagedBaseTool]) -> dict[str, StagedBaseTool]:
        tool_dict = {}
        for tool in tools:
            tool_config = getattr(tool, '_tool_config', None)
            if not tool_config:
                continue
            open_ai_tool = getattr(tool_config, 'open_ai_tool', None)
            if not open_ai_tool:
                continue
            function = getattr(open_ai_tool, 'function', None)
            if function and hasattr(function, 'name'):
                tool_dict[function.name] = tool
        return tool_dict
