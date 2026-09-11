from typing import Any

from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult


@inject
class _ToolSearchStageWrapper(TimedStageWrapper):

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        query = parameters.get("query", "")
        return f"> ##### Query:\n{query}\n" if query else ""

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        return f"> ##### Exception:\n{exception}\n"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        return f"> ##### Discovered tools:\n{result.content}\n"
