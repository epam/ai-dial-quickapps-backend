from typing import Any

from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult
from quickapp.common.utils import fenced_code_block


@inject
class _SkillReaderStageWrapper(TimedStageWrapper):

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        return ""

    def _get_stage_title_from_params(self, parameters: dict[str, Any]) -> str:
        """Name the skill, and the bundled file when one was requested.

        The base implementation stops at the first parameter marked
        ``show_value_in_stage_title``, which would show whichever of the two the
        model happened to serialize first.
        """
        skill_name = parameters.get("skill_name") or ""
        file_path = parameters.get("file_path")
        return f"{skill_name}/{file_path}" if file_path else str(skill_name)

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        return f"Error:\n{fenced_code_block(str(exception))}\n"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        return f"Skill Content:\n{fenced_code_block(result.content)}\n"
