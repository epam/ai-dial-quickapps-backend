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
from quickapp.common.chat_completion_stream.adopted_tool_stage import AdoptedToolStage
from quickapp.common.chat_completion_stream.argument_stream_presentation import (
    ArgumentStreamPresentation,
)
from quickapp.common.chat_completion_stream.tool_call import AccumulatedToolCall
from quickapp.common.payload_logging import log_payload
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
        self.__processors = sorted(processors, key=lambda p: p.order)
        self.__perf_timer: PerformanceTimer = perf_timer
        self.__period_name = "tool_execution"
        self.__argument_stream_presentations = self.__build_argument_stream_presentations(
            self.__tools
        )

    @property
    def argument_stream_presentations(self) -> dict[str, ArgumentStreamPresentation]:
        return self.__argument_stream_presentations

    async def execute(
        self,
        tool_call_list: list[AccumulatedToolCall],
        adopted_tool_stages: dict[str, AdoptedToolStage] | None = None,
    ) -> list[ToolCallResult]:
        adopted = adopted_tool_stages if adopted_tool_stages is not None else {}
        valid_calls: list[AccumulatedToolCall] = []
        tasks = []
        for tc in tool_call_list:
            tool = self.__tools.get(tc.name)
            if tool is None:
                continue
            args = json.loads(tc.arguments)
            logger.debug("Making tool call: %s", tc.name)
            log_payload(logger, "Making tool call: %s with args: %s", tc.name, args)
            adopted_stage = adopted.pop(tc.id, None)
            tasks.append(tool.arun(tool_call_id=tc.id, adopted_stage=adopted_stage, **args))
            valid_calls.append(tc)

        results: list[ToolCallResult] = list(await asyncio.gather(*tasks))
        self.__enrich_all(results)
        return [await self.__process_result(r, tc) for r, tc in zip(results, valid_calls)]

    def __enrich_all(self, results: list[ToolCallResult]) -> None:
        for enricher in self.__enrichers:
            for result in results:
                enricher.enrich(result)

    async def __process_result(
        self, result: ToolCallResult, tc: AccumulatedToolCall
    ) -> ToolCallResult:
        ctx = ProcessingContext(tool_call_id=tc.id, tool_name=tc.name)
        for processor in self.__processors:
            result = await processor.process(result, ctx)
        return result

    @staticmethod
    def __build_tool_dict(tools: list[StagedBaseTool]) -> dict[str, StagedBaseTool]:
        tool_dict = {}
        for tool in tools:
            name = tool.openai_function_name()
            if name:
                tool_dict[name] = tool
        return tool_dict

    @staticmethod
    def __build_argument_stream_presentations(
        tools: dict[str, StagedBaseTool],
    ) -> dict[str, ArgumentStreamPresentation]:
        presentations: dict[str, ArgumentStreamPresentation] = {}
        for name, tool in tools.items():
            presentation = tool.build_argument_stream_presentation()
            if presentation is not None:
                presentations[name] = presentation
        return presentations
