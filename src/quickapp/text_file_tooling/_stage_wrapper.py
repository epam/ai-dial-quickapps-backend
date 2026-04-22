from typing import Any

from injector import inject

from quickapp.common.timed_stage_wrapper import TimedStageWrapper
from quickapp.common.tool_call_result import ToolCallResult


@inject
class _TextFileStageWrapper(TimedStageWrapper):

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        return ""

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        return f"### Exception:\n\r{exception}\n\r"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        return f"### Result:\n\r{result.content}\n\r"
