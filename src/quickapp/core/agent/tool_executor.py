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
from quickapp.common.chat_completion_stream.tool_call import AccumulatedToolCall
from quickapp.common.model_hidden_tool import ModelHiddenTool
from quickapp.common.payload_logging import log_payload
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.tool_fallback.processor import FallbackProcessor
from quickapp.config.tools.tool_fallback import ContinueStrategyModel

logger = logging.getLogger(__name__)


class ToolExecutor:

    @inject
    def __init__(
        self,
        tools: list[StagedBaseTool],
        model_hidden_tools: list[ModelHiddenTool],
        enrichers: list[ToolCallResultEnricher],
        perf_timer: PerformanceTimer,
        processors: list[ToolCallResultProcessor],
    ):
        self.__tools: dict[str, StagedBaseTool] = self.__build_tool_dict(tools)
        self.__model_hidden_names: frozenset[str] = frozenset(
            self.__build_tool_dict(model_hidden_tools)
        )
        self.__enrichers = enrichers
        self.__processors = sorted(processors, key=lambda p: p.order)
        self.__perf_timer: PerformanceTimer = perf_timer
        self.__period_name = "tool_execution"

    async def execute(
        self,
        tool_call_list: list[AccumulatedToolCall],
        adopted_tool_stages: dict[str, AdoptedToolStage] | None = None,
    ) -> list[ToolCallResult]:
        adopted = adopted_tool_stages if adopted_tool_stages is not None else {}
        hidden_names = {
            tc.name
            for tc in tool_call_list
            if tc.name not in self.__tools and tc.name in self.__model_hidden_names
        }
        if hidden_names:
            logger.warning("Model requested model-hidden tool(s) %s", sorted(hidden_names))
        unknown_names = {
            tc.name
            for tc in tool_call_list
            if tc.name not in self.__tools and tc.name not in self.__model_hidden_names
        }
        if unknown_names:
            logger.error(
                "Model requested unknown tool(s) %s; registered=%s",
                sorted(unknown_names),
                sorted(self.__tools),
            )

        tasks = []
        for tc in tool_call_list:
            if tc.name not in self.__tools:
                if tc.name in self.__model_hidden_names:
                    tasks.append(self.__model_hidden_tool_result(tc))
                else:
                    tasks.append(self.__unknown_tool_result(tc))
                continue
            tool = self.__tools[tc.name]
            args = json.loads(tc.arguments)
            logger.debug("Making tool call: %s", tc.name)
            log_payload(logger, "Making tool call: %s with args: %s", tc.name, args)
            adopted_stage = adopted.pop(tc.id, None)
            tasks.append(tool.arun(tool_call_id=tc.id, adopted_stage=adopted_stage, **args))

        results: list[ToolCallResult] = list(await asyncio.gather(*tasks))
        self.__enrich_all(results)
        return [await self.__process_result(r, tc) for r, tc in zip(results, tool_call_list)]

    @staticmethod
    async def __unknown_tool_result(tc: AccumulatedToolCall) -> ToolCallResult:
        return FallbackProcessor.process_fallback(
            [
                ContinueStrategyModel(
                    instructions="This tool does not exist. Check the tool name and try again."
                )
            ],
            tc.id,
            RuntimeError(f"Unknown tool '{tc.name}'."),
        )

    @staticmethod
    async def __model_hidden_tool_result(tc: AccumulatedToolCall) -> ToolCallResult:
        return FallbackProcessor.process_fallback(
            [
                ContinueStrategyModel(
                    instructions=(
                        f"The tool '{tc.name}' is not available to you. The platform calls it "
                        "automatically; do not call it. Continue without it."
                    )
                )
            ],
            tc.id,
            RuntimeError(f"Tool '{tc.name}' is not available to the model."),
        )

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
