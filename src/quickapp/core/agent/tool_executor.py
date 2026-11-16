import asyncio
import json
import logging
from collections.abc import Awaitable

from injector import inject
from pydantic import BaseModel, ConfigDict

from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.abstract.tool_call_result_processor import (
    ProcessingContext,
    ToolCallResultProcessor,
)
from quickapp.common.chat_completion_stream.adopted_tool_stage import AdoptedToolStage
from quickapp.common.chat_completion_stream.tool_call import AccumulatedToolCall
from quickapp.common.deferred_tool_types import DeferredToolName
from quickapp.common.model_hidden_tool import ModelHiddenTool
from quickapp.common.payload_logging import log_payload
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.tool_fallback.processor import FallbackProcessor
from quickapp.common.tool_names import INTERNAL_TOOL_SEARCH_TOOL_NAME
from quickapp.config.tools.tool_fallback import ContinueStrategyModel
from quickapp.core.agent.lazy_loaded_tools_holder import LazyLoadedToolsHolder

logger = logging.getLogger(__name__)


class _Rejection(BaseModel):
    """Why a tool call is refused; both texts take the tool name as `{name}`."""

    model_config = ConfigDict(frozen=True)

    instructions: str
    error: str


_UNKNOWN = _Rejection(
    instructions="This tool does not exist. Check the tool name and try again.",
    error="Unknown tool '{name}'.",
)
_HIDDEN = _Rejection(
    instructions=(
        "The tool '{name}' is not available to you. The platform calls it automatically; "
        "do not call it. Continue without it."
    ),
    error="Tool '{name}' is not available to the model.",
)
_UNDISCOVERED = _Rejection(
    instructions=(
        "The tool '{name}' is not loaded, so its arguments could not be validated. "
        f"Call '{INTERNAL_TOOL_SEARCH_TOOL_NAME}' to load it, then retry the call."
    ),
    error="Tool '{name}' is deferred and not loaded.",
)


class ToolExecutor:

    @inject
    def __init__(
        self,
        tools: list[StagedBaseTool],
        model_hidden_tools: list[ModelHiddenTool],
        enrichers: list[ToolCallResultEnricher],
        perf_timer: PerformanceTimer,
        processors: list[ToolCallResultProcessor],
        deferred_tool_names: list[DeferredToolName],
        lazy_loaded_tools_holder: LazyLoadedToolsHolder,
    ):
        self.__deferred_names: frozenset[str] = frozenset(deferred_tool_names)
        self.__lazy_loaded_tools_holder = lazy_loaded_tools_holder
        self.__tools: dict[str, StagedBaseTool] = self.__build_tool_dict(tools)
        self.__model_hidden_names: frozenset[str] = frozenset(
            self.__build_tool_dict(model_hidden_tools)
        )
        self.__enrichers = enrichers
        self.__processors = sorted(processors, key=lambda p: p.order)
        self.__perf_timer: PerformanceTimer = perf_timer

    async def execute(
        self,
        tool_call_list: list[AccumulatedToolCall],
        adopted_tool_stages: dict[str, AdoptedToolStage] | None = None,
    ) -> list[ToolCallResult]:
        adopted = adopted_tool_stages if adopted_tool_stages is not None else {}
        rejected: dict[_Rejection, set[str]] = {}
        tasks = []
        for tc in tool_call_list:
            rejection = self.__find_rejection(tc)
            if rejection is None:
                tasks.append(self.__start_call(tc, adopted))
                continue
            rejected.setdefault(rejection, set()).add(tc.name)
            tasks.append(self.__rejected_result(tc, rejection))
        self.__log_rejections(rejected)

        results: list[ToolCallResult] = list(await asyncio.gather(*tasks))
        self.__enrich_all(results)
        return [await self.__process_result(r, tc) for r, tc in zip(results, tool_call_list)]

    def __find_rejection(self, tc: AccumulatedToolCall) -> _Rejection | None:
        """Why the call must not run, or None when it can."""
        if tc.name not in self.__tools:
            return _HIDDEN if tc.name in self.__model_hidden_names else _UNKNOWN
        if tc.name in self.__deferred_names and not self.__lazy_loaded_tools_holder.contains(
            tc.name
        ):
            # Its schema is not in `tools`, so the arguments were guessed.
            return _UNDISCOVERED
        return None

    def __start_call(
        self, tc: AccumulatedToolCall, adopted: dict[str, AdoptedToolStage]
    ) -> Awaitable[ToolCallResult]:
        args = json.loads(tc.arguments)
        logger.debug("Making tool call: %s", tc.name)
        log_payload(logger, "Making tool call: %s with args: %s", tc.name, args)
        return self.__tools[tc.name].arun(
            tool_call_id=tc.id, adopted_stage=adopted.pop(tc.id, None), **args
        )

    def __log_rejections(self, rejected: dict[_Rejection, set[str]]) -> None:
        if names := rejected.get(_HIDDEN):
            logger.warning("Model requested model-hidden tool(s) %s", sorted(names))
        if names := rejected.get(_UNDISCOVERED):
            logger.warning(
                "Model called deferred tool(s) %s without a loaded schema", sorted(names)
            )
        if names := rejected.get(_UNKNOWN):
            logger.error(
                "Model requested unknown tool(s) %s; registered=%s",
                sorted(names),
                sorted(self.__tools),
            )

    @staticmethod
    async def __rejected_result(tc: AccumulatedToolCall, rejection: _Rejection) -> ToolCallResult:
        return FallbackProcessor.process_fallback(
            [ContinueStrategyModel(instructions=rejection.instructions.format(name=tc.name))],
            tc.id,
            RuntimeError(rejection.error.format(name=tc.name)),
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
