import asyncio
import json
import logging

from injector import inject

from quickapp.common import CompletionResult, StagedBaseTool
from quickapp.common.abstract.completion_result_enricher import CompletionResultEnricher
from quickapp.common.chat_completion_stream.tool_call import AccumulatedToolCall
from quickapp.common.perf_timer.perf_timer import PerformanceTimer

logger = logging.getLogger(__name__)


class ToolExecutor:

    @inject
    def __init__(
        self,
        tools: list[StagedBaseTool],
        enrichers: list[CompletionResultEnricher],
        perf_timer: PerformanceTimer,
    ):
        self.__tools: dict[str, StagedBaseTool] = self.__build_tool_dict(tools)
        self.__enrichers = enrichers
        self.__perf_timer: PerformanceTimer = perf_timer
        self.__period_name = "tool_execution"

    async def execute(self, tool_call_list: list[AccumulatedToolCall]) -> list[CompletionResult]:
        tasks = []
        for tc in tool_call_list:
            tool = self.__tools.get(tc.name)

            args = json.loads(tc.arguments)

            logger.debug(f"Making tool calls: {tc.name} with args:{args}")
            if tool:
                tasks.append(tool.arun(tool_call_id=tc.id, **args))

        results = await asyncio.gather(*tasks, return_exceptions=False)

        for enricher in self.__enrichers:
            for result in results:
                enricher.enrich(result)

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
