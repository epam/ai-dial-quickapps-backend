from typing import Any

from injector import inject

from quickapp.common import CompletionResult, TimedStageWrapper


@inject
class _SkillReaderStageWrapper(TimedStageWrapper):

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        """Format the parameters for display in the stage."""
        if file_name := parameters.get("file_name"):
            return f"**File:** {file_name}"
        return ""

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        """Build debug information from an exception."""
        return f"### Error:\n{exception}\n"

    def _build_debug_info_from_result(self, result: CompletionResult) -> str:
        """Build debug information from the result."""
        return f"### Skill Content:\n{result.content}\n"
