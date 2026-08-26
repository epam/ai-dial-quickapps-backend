from typing import Any

from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult


@inject
class _SubagentStageWrapper(TimedStageWrapper):

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        # The tool sets are shown because the coordinator picks them per spawn: without
        # them the user cannot tell why one subagent could search the web and the next
        # one could not.
        tool_sets = parameters.get("tool_sets") or []
        rendered = ", ".join(str(name) for name in tool_sets) if tool_sets else "none"
        return f"**Task:** {parameters.get('prompt', '')}\n\n**Tools:** {rendered}\n\n"

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        return f"### Exception:\n\r{exception}\n\r"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        return f"### Result:\n\r{result.content}\n\r"
