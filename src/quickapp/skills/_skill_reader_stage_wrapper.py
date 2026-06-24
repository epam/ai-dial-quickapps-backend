from typing import Any

from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult
from quickapp.common.utils import fenced_code_block


@inject
class _SkillReaderStageWrapper(TimedStageWrapper):

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        return ""

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        return f"Error:\n{fenced_code_block(str(exception))}\n"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        return f"Skill Content:\n{fenced_code_block(result.content)}\n"
