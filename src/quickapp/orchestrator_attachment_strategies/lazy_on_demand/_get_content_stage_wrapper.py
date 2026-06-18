from typing import Any

from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult


@inject
class _GetContentStageWrapper(TimedStageWrapper):

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        url = parameters.get("attachment_url")
        return str(url) if url is not None else ""

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        return f"\n\r### Exception:\n\r{exception}\n\r"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        return f"\n\r### Get content file:\n\r{result.content}\n\r"
