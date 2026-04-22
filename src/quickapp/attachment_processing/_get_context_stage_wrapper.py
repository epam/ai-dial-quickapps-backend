from typing import Any

from injector import inject

from quickapp.common import CompletionResult, TimedStageWrapper


@inject
class _GetContextStageWrapper(TimedStageWrapper):

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        url = parameters.get("context_url")
        return str(url) if url is not None else ""

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        return f"### Exception:\n\r{exception}\n\r"

    def _build_debug_info_from_result(self, result: CompletionResult) -> str:
        return f"### Get context file:\n\r{result.content}\n\r"
