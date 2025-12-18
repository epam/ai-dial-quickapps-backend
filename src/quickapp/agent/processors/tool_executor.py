import asyncio
import logging
from typing import Dict, List

from aidial_sdk.chat_completion import ToolCall
from injector import inject

from quickapp.common import CompletionResult, StagedBaseTool
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.utils import sanitize_toolname

logger = logging.getLogger(__name__)


class ToolExecutor:

    @inject
    def __init__(self, tools: list[StagedBaseTool], perf_timer: PerformanceTimer):
        self.__tools: dict[str, StagedBaseTool] = self.__build_tool_dict(tools)
        self.__perf_timer: PerformanceTimer = perf_timer
        self.__period_name = "tool_execution"

    async def execute(self, tool_call_list: List[ToolCall]) -> List[CompletionResult]:
        tasks = []
        for tc in tool_call_list:
            tool = self.__tools.get(tc.function.name)

            # Hack, cause tc.function.arguments from agent returns json-like string
            import json

            args = json.loads(tc.function.arguments)

            logger.debug(f"Making tool calls: {tc.function.name} with args:{args}")
            if tool:
                tasks.append(tool.arun(tool_call_id=tc.id, **args))
        # fill tool calls here?
        results = await asyncio.gather(*tasks, return_exceptions=False)

        return results

    @staticmethod
    def __build_tool_dict(tools: List[StagedBaseTool]) -> Dict[str, StagedBaseTool]:
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
                # Sanitize tool name to ensure consistency. Orchestrator make a call to function with sanitized name. So we need to build dict also using sanitized names
                tool_name = sanitize_toolname(function.name)
                tool_dict[tool_name] = tool
        return tool_dict

    @staticmethod
    def _find_tool_call_by_id(tool_call_id, tool_call_list: List[ToolCall]):
        for tc in tool_call_list:
            if tc.id == tool_call_id:
                return tc
        raise RuntimeError(f"The {tool_call_id} is not found in the {tool_call_list}")
