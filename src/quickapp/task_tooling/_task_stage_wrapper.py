from typing import Any

from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult
from quickapp.common.exceptions.tool_error import ToolErrorException
from quickapp.common.utils import fenced_code_block

from ._tool_config import INHERIT_TOOLS, is_inherit


def _format_tools(tools: Any) -> str:
    """`tools` as the user reads it: inherit, a comma-separated list, or none."""
    if is_inherit(tools):
        return INHERIT_TOOLS
    if isinstance(tools, list):
        return ", ".join(str(name) for name in tools) or "none"
    return str(tools)


@inject
class _TaskStageWrapper(TimedStageWrapper):

    def _get_stage_title_from_params(self, parameters: dict[str, Any]) -> str:
        name = parameters.get("name")
        return f": {name}" if name else ""

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        prompt = str(parameters.get("prompt", ""))
        return (
            f"**Prompt:**\n{fenced_code_block(prompt)}\n\n"
            f"**Tools:** {_format_tools(parameters.get('tools'))}\n\n"
        )

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        if isinstance(exception, ToolErrorException):
            return f"### Error:\n\r{fenced_code_block(exception.user_facing_message)}\n\r"
        return (
            f"### Exception:\n\r{fenced_code_block(f'{type(exception).__name__}: {exception}')}\n\r"
        )

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        return f"### Result:\n\r{fenced_code_block(result.content)}\n\r"
