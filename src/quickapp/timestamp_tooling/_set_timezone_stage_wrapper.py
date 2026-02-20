from typing import Any

from injector import inject

from quickapp.common import CompletionResult, TimedStageWrapper


@inject
class _SetTimezoneStageWrapper(TimedStageWrapper):

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        return ""

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        return f"### Exception:\n\r{exception}\n\r"

    def _build_debug_info_from_result(self, result: CompletionResult) -> str:
        return f"### Result:\n\r{result.content}\n\r"
