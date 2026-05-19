from typing import Any

from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult


@inject
class _SkillReaderStageWrapper(TimedStageWrapper):

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        """Format the parameters for display in the stage."""
        if skill_name := parameters.get("skill_name"):
            return f"Skill: {skill_name}"
        return ""

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        return f"Error:\n```\n{exception}\n```\n"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        return f"Skill Content:\n```\n{result.content}\n```\n"
