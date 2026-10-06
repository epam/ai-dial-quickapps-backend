from typing import Any

from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult
from quickapp.common.exceptions.tool_error import ToolErrorException
from quickapp.common.utils import fenced_code_block


@inject
class _SubagentStageWrapper(TimedStageWrapper):

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        header = f"**Subagent:** {parameters.get('subagent_type', '')}\n\n"
        header += f"**Task:** {parameters.get('prompt', '')}\n\n"
        return header

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        if isinstance(exception, ToolErrorException):
            return f"### Error:\n\r{fenced_code_block(exception.user_facing_message)}\n\r"
        return (
            f"### Exception:\n\r{fenced_code_block(f'{type(exception).__name__}: {exception}')}\n\r"
        )

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        return f"### Result:\n\r{fenced_code_block(result.content)}\n\r"
