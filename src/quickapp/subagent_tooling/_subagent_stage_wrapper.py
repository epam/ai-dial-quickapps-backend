from typing import Any

from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult


@inject
class _SubagentStageWrapper(TimedStageWrapper):

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        header = f"**Subagent:** {parameters.get('subagent_type', '')}\n\n"
        header += f"**Task:** {parameters.get('prompt', '')}\n\n"
        # Shown only when the coordinator picked the tools itself (general-purpose):
        # without it the user cannot tell why one spawn could search and the next could not.
        tool_sets = parameters.get("tool_sets")
        if tool_sets is not None:
            rendered = ", ".join(str(name) for name in tool_sets) or "none"
            header += f"**Tools:** {rendered}\n\n"
        return header

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        return f"### Exception:\n\r{exception}\n\r"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        return f"### Result:\n\r{result.content}\n\r"
